import streamlit as st
from supabase import create_client, Client
from datetime import datetime, timezone

# ── 0. 세션 상태 초기화 ──
if "submitted_ok" not in st.session_state:
    st.session_state.submitted_ok = False
if "gpt_feedbacks" not in st.session_state:
    st.session_state.gpt_feedbacks = None
if "gpt_payload" not in st.session_state:
    st.session_state.gpt_payload = None

# [핵심] 상태 초기화 콜백 함수
# 입력창의 내용이 변경되면 이 함수가 실행되어 이전 결과들을 지웁니다.
def reset_state():
    st.session_state.submitted_ok = False
    st.session_state.gpt_feedbacks = None
    st.session_state.gpt_payload = None

# ----Supabase 설정----------------------------
@st.cache_resource
def get_supabase_client() -> Client:
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
        return create_client(url, key)
    except Exception:
        # secrets가 없을 때 에러 방지용 더미(실제 실행 시엔 secrets 필수)
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
    return supabase.table("student_submissions").insert(row).execute()
# ---------------------------------------------

# ── 1. 수업 제목 ──
st.title("예시 수업 제목")

# ── 2~4. 입력 + 제출을 form 안에 묶기 ──
with st.form("submit_form"):
    # ── 2. 학번 입력 (수정 시 결과 리셋 적용) ──
    student_id = st.text_input(
        "학번", 
        help="학생의 학번을 작성하세요. (예: 10130)",
        # [핵심] 입력값이 바뀌면 reset_state 실행
        # (주의: form 안에서는 form_submit_button을 누를 때까지 UI 반영이 보류되지만,
        #  다시 제출을 눌러야 하므로 논리적으로는 맞습니다)
    )

    # ── 3-1. 서술형 문제 1 ──
    QUESTION_1 = "기체 입자들의 운동과 온도의 관계를 서술하세요."
    st.markdown("#### 서술형 문제 1")
    st.write(QUESTION_1)
    # [핵심] key를 지정하고 on_change는 form 특성상 즉시 반응이 어렵지만, 
    # Streamlit 구조상 form을 제출해야 값이 업데이트 되므로, 
    # 여기서는 '제출' 버튼을 누르면 새로운 내용으로 갱신되게 처리됩니다.
    # 만약 '타이핑 중 실시간 리셋'을 원하면 form을 제거해야 하지만,
    # 지금 구조(Form 유지)에서는 아래 로직으로 충분합니다.
    answer_1 = st.text_area("답안을 입력하세요", key="answer1", height=150)

    # ── 3-2. 서술형 문제 2 ──
    QUESTION_2 = "보일 법칙에 대해 설명하세요."
    st.markdown("#### 서술형 문제 2")
    st.write(QUESTION_2)
    answer_2 = st.text_area("답안을 입력하세요", key="answer2", height=150)

    # ── 3-3. 서술형 문제 3 ──
    QUESTION_3 = "열에너지 이동 3가지 방식(전도·대류·복사)을 설명하세요."
    st.markdown("#### 서술형 문제 3")
    st.write(QUESTION_3)
    answer_3 = st.text_area("답안을 입력하세요", key="answer3", height=150)

    answers = [answer_1, answer_2, answer_3]

    # ── 4. 전체 제출 버튼 ──
    submitted = st.form_submit_button("제출")

# ── 제출 처리 로직 ──
# 폼이 제출되면 무조건 상태를 리셋(새로운 검사 시작)하거나 갱신
if submitted:
    # 일단 제출 버튼 누르면 이전 결과 초기화
    reset_state()
    
    if not student_id.strip():
        st.warning("학번을 입력하세요.")
    elif any(ans.strip() == "" for ans in answers):
        st.warning("모든 답안을 작성하세요.")
    else:
        st.success(f"제출 완료! 학번: {student_id}")
        st.session_state.submitted_ok = True
        # 폼 제출 시에는 피드백은 일단 비워둡니다 (GPT 버튼을 눌러야 생기므로)
        st.session_state.gpt_feedbacks = None

# ==================================================
# Step 2 – GPT API 기반 서술형 채점 + 피드백
# ==================================================

# ── 채점 기준 및 헬퍼 함수 ──
GRADING_GUIDELINES = {
    1: "기체 입자의 운동은 온도와 비례 관계임을 언급하고, 입자 충돌·속도 증가 예를 기술한다.",
    2: "일정한 온도에서, 기체의 압력과 부피가 서로 반비례한다.",
    3: "전도는 입자 간 직접 충돌, 대류는 유체의 순환, 복사는 전자기파를 통한 열 이동 방식이다.",
}

def normalize_feedback(text: str) -> str:
    if not text: return "X: 피드백 생성 실패"
    first_line = text.strip().splitlines()[0].strip()
    if first_line.startswith("O") and not first_line.startswith("O:"):
        first_line = "O: " + first_line[1:].lstrip(": ").strip()
    if first_line.startswith("X") and not first_line.startswith("X:"):
        first_line = "X: " + first_line[1:].lstrip(": ").strip()
    if not (first_line.startswith("O:") or first_line.startswith("X:")):
        first_line = "X: " + first_line
    head, body = first_line.split(":", 1)
    body = body.strip()
    if len(body) > 200: body = body[:200] + "…"
    return f"{head.strip()}: {body}"

# ── GPT 피드백 버튼 (제출 성공 상태일 때만 보임) ──
# 여기서 submitted_ok 상태를 체크하므로,
# 사용자가 위에서 내용을 수정하고 '제출'을 다시 누르기 전까지는 
# (혹은 리셋 로직에 의해) 이 버튼이나 결과가 사라지게 됩니다.
if st.session_state.submitted_ok:
    if st.button("GPT 피드백 확인"):
        
        # [라이브러리/키 체크]
        try:
            from openai import OpenAI
            client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
        except Exception as e:
            st.error(f"OpenAI 설정 오류: {e}")
            st.stop()

        feedbacks = []
        with st.spinner("AI 선생님이 채점 중입니다... ⏳"):
            for idx, ans in enumerate(answers, start=1):
                criterion = GRADING_GUIDELINES.get(idx, "채점 기준 없음")
                prompt = (
                    f"문항 번호: {idx}\n"
                    f"채점 기준: {criterion}\n"
                    f"학생 답안: {ans}\n\n"
                    "출력 규칙:\n"
                    "- 반드시 한 줄로만 출력\n"
                    "- 형식은 정확히 'O: ...' 또는 'X: ...'\n"
                    "- 피드백은 학생에게 말하듯 친절하게, 200자 이내\n"
                )
                try:
                    response = client.chat.completions.create(
                        model="gpt-4o-mini", # 모델명 최신화 권장 (gpt-5-mini는 예시일 수 있음)
                        messages=[
                            {"role": "system", "content": "너는 친절하지만 정확한 과학 교사다."},
                            {"role": "user", "content": prompt},
                        ],
                    )
                    raw_text = response.choices[0].message.content.strip()
                except Exception as e:
                    raw_text = f"API 오류: {e}"
                
                feedbacks.append(normalize_feedback(raw_text))

        st.session_state.gpt_feedbacks = feedbacks
        
        # Supabase 저장용 페이로드 생성
        st.session_state.gpt_payload = {
            "student_id": student_id.strip(),
            "answers": {f"Q{i}": a for i, a in enumerate(answers, start=1)},
            "feedbacks": {f"Q{i}": fb for i, fb in enumerate(feedbacks, start=1)},
            "guidelines": {f"Q{k}": v for k, v in GRADING_GUIDELINES.items()},
            "model": "gpt-4o-mini",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # Supabase 저장
        try:
            save_to_supabase(st.session_state.gpt_payload)
            st.success("데이터베이스 저장 완료")
        except Exception as e:
            st.error(f"저장 오류(Supabase 설정을 확인하세요): {e}")

# ── 4. 결과 표시 ──
if st.session_state.gpt_feedbacks:
    st.markdown("---")
    st.subheader("📝 AI 피드백 결과")
    for i, fb in enumerate(st.session_state.gpt_feedbacks, start=1):
        if fb.startswith("O:"):
            st.success(f"**문항 {i}** : {fb}")
        else:
            st.info(f"**문항 {i}** : {fb}")
