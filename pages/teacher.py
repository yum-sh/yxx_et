"""
교사용 대시보드 - teacher.py (Supabase 버전)
─────────────────────────────────────────────────────────────────
• student_submissions 테이블 실시간 모니터링
• "새로고침" 버튼 → 최신 데이터 즉시 갱신
• 학번(부분) 검색, 최근 N일 필터, CSV 다운로드
• (추가) 통계: 총 제출 수, 고유 학생 수, 문항별 O 비율
• (추가) 시각화: 문항별 정답률 막대그래프 (Altair 적용)
• (추가) 개인별 피드백 조회: 특정 학번의 제출 이력 확인
"""

import streamlit as st
import pandas as pd
import altair as alt  # 시각화를 위해 추가
from supabase import create_client, Client
from datetime import datetime, timedelta, timezone

# UI 레이아웃
st.set_page_config(page_title="교사용 대시보드", layout="wide") 

# [추가] 간단한 비밀번호 보호 기능
password = st.sidebar.text_input("교사 인증 암호", type="password")
if password != "1234":  # 원하는 비밀번호로 변경하세요
    st.warning("선생님만 접근할 수 있습니다.")
    st.stop()  # 암호가 틀리면 여기서 코드 실행 중단

# =========================================================
# 1) Supabase 연결
# =========================================================
@st.cache_resource
def get_supabase_client() -> Client:
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
        return create_client(url, key)
    except Exception:
        st.error("Supabase 연결 설정(secrets)을 확인해주세요.")
        st.stop()

# =========================================================
# 2) 데이터 로드
# =========================================================
@st.cache_data(show_spinner=False, ttl=30)
def fetch_data(search_id: str, days: int) -> pd.DataFrame:
    try:
        supabase = get_supabase_client()

        q = (
            supabase.table("student_submissions")
            .select(
                "id, student_id, answer_1, answer_2, answer_3, "
                "feedback_1, feedback_2, feedback_3, model, created_at"
            )
        )

        # 학번 부분 검색 (대소문자 무시 검색)
        if search_id:
            q = q.ilike("student_id", f"%{search_id}%")

        # 최근 N일 필터
        if days and days > 0:
            date_from = datetime.now(timezone.utc) - timedelta(days=int(days))
            q = q.gte("created_at", date_from.isoformat())

        # 최신순 정렬
        q = q.order("created_at", desc=True)

        res = q.execute()
        rows = res.data or []
        df = pd.DataFrame(rows)

        if not df.empty and "created_at" in df.columns:
            df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")

        return df

    except Exception as e:
        st.error(f"Supabase 조회 오류: {e}")
        return pd.DataFrame()

@st.cache_data(show_spinner=False, ttl=30)
def fetch_student_history(student_id: str, limit: int = 200) -> pd.DataFrame:
    """특정 학번의 제출 이력을 별도로 조회"""
    try:
        supabase = get_supabase_client()
        q = (
            supabase.table("student_submissions")
            .select(
                "id, student_id, answer_1, answer_2, answer_3, "
                "feedback_1, feedback_2, feedback_3, model, created_at"
            )
            .eq("student_id", student_id)
            .order("created_at", desc=True)
            .limit(limit)
        )
        res = q.execute()
        rows = res.data or []
        df = pd.DataFrame(rows)
        if not df.empty and "created_at" in df.columns:
            df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
        return df
    except Exception as e:
        st.error(f"개인 이력 조회 오류: {e}")
        return pd.DataFrame()

# =========================================================
# 3) UI 레이아웃
# =========================================================
st.title("📊 대시보드 — 서술형 평가 (Supabase)")

col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    search_id = st.text_input("학번 검색 (부분 가능)", value="")
with col2:
    days = st.number_input("최근 N일", min_value=0, max_value=365, value=30, step=1)
with col3:
    if st.button("🔄 새로고침"):
        st.cache_data.clear()

df = fetch_data(search_id=search_id.strip(), days=int(days))

# =========================================================
# 4) 상단 통계(전체/학생 수/문항별 O 비율) + 그래프
# =========================================================
st.write(f"**총 {len(df)} 건** 표시 중")

if df.empty:
    st.info("조건에 해당하는 데이터가 없습니다.")
else:
    unique_students = df["student_id"].nunique() if "student_id" in df.columns else 0
    latest_time = df["created_at"].max() if "created_at" in df.columns else None

    # 기본 메트릭 표시
    c1, c2, c3 = st.columns(3)
    c1.metric("총 제출 수", f"{len(df)}")
    c2.metric("고유 학생 수", f"{unique_students}")
    c3.metric("최신 제출", f"{latest_time}" if latest_time is not None else "-")

    # ---------------------------------------------------------
    # [수정됨] 정답률 계산 로직
    # ---------------------------------------------------------
    def o_rate(series: pd.Series) -> float:
        if series is None or series.empty:
            return 0.0
        s = series.fillna("").astype(str)
        # "O:"로 시작하는 건수를 전체 건수로 나눔
        return (s.str.startswith("O:").sum() / len(s)) * 100.0

    r1 = o_rate(df.get("feedback_1"))
    r2 = o_rate(df.get("feedback_2"))
    r3 = o_rate(df.get("feedback_3"))

    st.markdown("---")
    st.markdown("#### ✅ 문항별 정답률 (O 비율)")

    # ---------------------------------------------------------
    # [추가됨] 시각화: Altair 막대그래프
    # ---------------------------------------------------------
    
    # 그래프를 그리기 위한 데이터프레임 생성
    chart_df = pd.DataFrame({
        "문항": ["문항 1", "문항 2", "문항 3"],
        "정답률": [r1, r2, r3]
    })

    # Altair 차트 생성
    # 1. 막대 그래프 (Y축 범위를 0~100으로 고정하여 왜곡 방지)
    bar_chart = alt.Chart(chart_df).mark_bar().encode(
        x=alt.X('문항', axis=alt.Axis(labelAngle=0, title=None)), # X축 라벨 회전 방지
        y=alt.Y('정답률', scale=alt.Scale(domain=[0, 100]), title="정답률 (%)"), # 0~100 고정
        color=alt.Color('문항', legend=None), # 문항별 다른 색상
        tooltip=['문항', alt.Tooltip('정답률', format='.1f')] # 마우스 오버 시 수치 표시
    ).properties(
        height=300 # 그래프 높이 설정
    )

    # 2. 막대 위에 텍스트(숫자) 표시
    text_labels = bar_chart.mark_text(
        align='center',
        baseline='bottom',
        dy=-5,  # 막대 위로 살짝 띄움
        fontSize=14
    ).encode(
        text=alt.Text('정답률', format='.1f')
    )

    # 차트와 텍스트 결합 후 출력
    st.altair_chart(bar_chart + text_labels, use_container_width=True)

    # (기존 텍스트 메트릭도 작게 표시하고 싶다면 아래 주석 해제)
    # s1, s2, s3 = st.columns(3)
    # s1.metric("문항 1", f"{r1:.1f}%")
    # s2.metric("문항 2", f"{r2:.1f}%")
    # s3.metric("문항 3", f"{r3:.1f}%")

    # =========================================================
    # 5) 전체 목록 표시 + CSV 다운로드
    # =========================================================
    st.markdown("---")
    st.subheader("📄 전체 제출 목록")

    show_cols = [
        "student_id", "created_at",
        "answer_1", "answer_2", "answer_3",
        "feedback_1", "feedback_2", "feedback_3",
        "model"
    ]
    show_cols = [c for c in show_cols if c in df.columns]
    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)

    csv = df[show_cols].to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 CSV 다운로드",
        csv,
        file_name="student_submissions.csv",
        mime="text/csv",
    )

    # =========================================================
    # 6) 개인별 피드백 조회
    # =========================================================
    st.markdown("---")
    st.subheader("🔎 개인별 피드백 조회")

    student_list = sorted(df["student_id"].dropna().astype(str).unique().tolist())
    selected = st.selectbox("학번 선택", options=student_list)

    if selected:
        history = fetch_student_history(selected, limit=200)
        st.write(f"**{selected} 제출 이력: {len(history)}건**")

        if history.empty:
            st.info("이 학번의 이력이 없습니다.")
        else:
            hist_cols = [
                "created_at",
                "answer_1", "feedback_1",
                "answer_2", "feedback_2",
                "answer_3", "feedback_3",
                "model",
            ]
            hist_cols = [c for c in hist_cols if c in history.columns]
            st.dataframe(history[hist_cols], use_container_width=True, hide_index=True)
