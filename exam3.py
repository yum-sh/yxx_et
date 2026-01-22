import streamlit as st
from supabase import create_client, Client
from datetime import datetime, timezone
import time

# ── 0. 기본 설정 및 세션 초기화 ──
st.set_page_config(page_title="AI 서술형 평가", layout="centered")

# 결과 저장용 세션 변수 (리런 되어도 결과 유지)
if "gpt_feedbacks" not in st.session_state:
    st.session_state.gpt_feedbacks = None

# ----Supabase 연결 설정----------------------------
@st.cache_resource
def get_supabase_client() -> Client:
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
        return create_client(url, key)
    except Exception:
        return None

def save_to_supabase(payload: dict):
    supabase = get_supabase_client()
    if not supabase:
        return None
    
    row = {
        "student_id": payload["student_id"],
        "answer_1": payload["answers"]["Q1"],
        "answer_2": payload["answers"]["Q2"],
        "answer_3": payload["answers"]["Q3"],
        "feedback_1": payload["feedbacks"]["Q1"],
        "feedback_2": payload["feedbacks"]["Q2"],
        "feedback_3": payload["feedbacks"]["Q3"],
        "guideline_1": payload["guidelines"]["Q1"],
        "guideline_2": payload["guidelines"]["Q2"],
        "guideline_3": payload["guidelines"]["Q3"],
        "model": payload["model"],
    }
    # insert 후 execute()를 호출해야 실제 저장됨
    return supabase.table("student_submissions").insert(row).execute()
# --------------------------------------------------

# ── 1. 채점 기준 및 도구 함수 ──
GRADING_GUIDELINES = {
    1: "기체 입자의 운동은 온도와 비례 관계임을 언급하고, 입자 충돌·속도 증가 예를 기술한다.",
    2: "일정한 온도에서, 기체의 압력과 부피가 서로 반비례한다.",
    3: "전도는 입자 간 직접 충돌, 대류는 유체의 순환, 복사는 전자기파를 통한 열 이동 방식이다.",
}

def normalize_feedback(text: str) -> str:
    """AI 응답 형식을 'O: ...' 또는 'X: ...' 형태로 보정"""
    if not text: return "X: 피드백 생성 실패"
    first_line = text.strip().splitlines()[0].strip()
    
    if first_line.startswith("O") and not first_line.startswith("O:"):
        first_line = "O: " + first_line[1:].lstrip(": ").strip()
    if first_line.startswith("X") and not first_line.startswith("X:"):
        first_line = "X: " + first_line[1:].lstrip(": ").strip()
    
    # O나 X로 시작 안 하면 X로 간주
    if not (first_line.startswith("O:") or first_line.startswith("X:")):
        first_line = "X: " + first_line
        
    head, body = first_line.split(":", 1)
    body = body.strip()
    if len(body) > 200: body = body[:200] + "…"
    return f"{head.strip()}: {body}"

# ── 2. UI 구성 (제목 및 입력 폼) ──
st.title("과학 서술형 평가")

with st.form("submit_form"):
    student_id = st.text_input("학번", placeholder="예: 10130")

    st.markdown("#### Q1. 기체 입자들의 운동과 온도의 관계")
    st.info(f"💡 채점 포인트: {GRADING_GUIDELINES[1]}")
    answer_1 = st.text_area("답안 1", height=100, label_visibility="collapsed")

    st.markdown("#### Q2. 보일 법칙")
    st.info(f"💡 채점 포인트: {GRADING_GUIDELINES[2]}")
    answer_2 = st.text_area("답안 2", height=100, label_visibility="collapsed")

    st.markdown("#### Q3. 열에너지 이동 3가지 방식")
    st.info(f"💡 채점 포인트: {GRADING_GUIDELINES[3]}")
    answer_3 = st.text_area("답안 3", height=100, label_visibility="collapsed")

    # ── [핵심] 버튼 하나로 통합 ──
    # 이 버튼을 누르면 아래 로직이 즉시 실행됩니다.
    submitted = st.form_submit_button("제출 및 AI 채점 확인", type="primary")

# ── 3. 제출 버튼 클릭 시 실행 로직 ──
if submitted:
    # (1) 유효성 검사
    answers = [answer_1, answer_2, answer_3]
    if not student_id.strip():
        st.warning("⚠️ 학번을 먼저 입력해주세요.")
        st.stop()
    if any(a.strip() == "" for a in answers):
        st.warning("⚠️ 모든 문제의 답안을 작성해주세요.")
        st.stop()

    # (2) 이전 결과 지우기 (사실 변수 덮어쓰기로 자동 해결되지만 명시적으로)
    st.session_state.gpt_feedbacks = None
    
    # (3) OpenAI API 호출 준비
    try:
        from openai import OpenAI
        client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
    except Exception as e:
        st.error(f"설정 오류: {e}")
        st.stop()

    new_feedbacks = []
    
    # (4) 채점 진행 (Spinner로 대기 표시)
    with st.spinner("AI 선생님이 답안을 분석하고 있습니다... (약 3~5초 소요)"):
        for idx, ans in enumerate(answers, start=1):
            criterion = GRADING_GUIDELINES.get(idx, "")
            prompt = (
                f"문항: {idx}\n기준: {criterion}\n답안: {ans}\n\n"
                "규칙: 한 줄 출력, 'O: 설명' 또는 'X: 설명' 형식 유지, 친절하게 200자 이내."
            )
            
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini", # 모델명
                    messages=[
                        {"role": "system", "content": "너는 친절하고 명확한 과학 교사다."},
                        {"role": "user", "content": prompt}
                    ]
                )
                text = response.choices[0].message.content.strip()
                new_feedbacks.append(normalize_feedback(text))
            except Exception as e:
                new_feedbacks.append(f"X: 에러 발생 ({e})")

        # (5) DB 저장 (Supabase)
        payload = {
            "student_id": student_id.strip(),
            "answers": {f"Q{i}": a for i, a in enumerate(answers, start=1)},
            "feedbacks": {f"Q{i}": fb for i, fb in enumerate(new_feedbacks, start=1)},
            "guidelines": {f"Q{k}": v for k, v in GRADING_GUIDELINES.items()},
            "model": "gpt-4o-mini"
        }
        
        try:
            save_to_supabase(payload)
            # (6) 결과 세션 업데이트 (화면 표시용)
            st.session_state.gpt_feedbacks = new_feedbacks
            st.success("✅ 채점 및 제출이 완료되었습니다!")
            
        except Exception as e:
            st.error(f"저장 중 오류가 발생했습니다: {e}")

# ── 4. 결과 화면 표시 (버튼 클릭 직후 바로 렌더링됨) ──
if st.session_state.gpt_feedbacks:
    st.divider()
    st.subheader(f"📝 {student_id}님의 채점 결과")
    
    for i, fb in enumerate(st.session_state.gpt_feedbacks, start=1):
        if fb.startswith("O:"):
            st.success(f"**Q{i} 결과** : {fb}")
        else:
            st.error(f"**Q{i} 결과** : {fb}")  # X는 빨간색(error)나 파란색(info)으로 표시

    st.caption("※ 결과는 선생님께 자동 전송되었습니다. 내용을 수정하고 다시 제출하면 새로운 피드백을 받을 수 있습니다.")
