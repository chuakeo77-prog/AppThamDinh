import streamlit as st
import json
import os
import math
import hashlib
from datetime import datetime
import pandas as pd

# ============================================================
# APP THẨM ĐỊNH CHO VAY KHÁCH HÀNG CÁ NHÂN
# Công cụ hỗ trợ phân tích sơ bộ, không thay thế quy trình phê duyệt.
# ============================================================

st.set_page_config(
    page_title="LoanCheck | Thẩm định cho vay cá nhân",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

DATA_DIR = "."
HISTORY_FILE = os.path.join(DATA_DIR, "loan_applications.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "loan_settings.json")

DEFAULT_SETTINGS = {
    "admin_username": "admin",
    "admin_password_hash": hashlib.sha256("123456".encode()).hexdigest(),
    "max_dti": 40.0,
    "max_ltv": 80.0,
    "min_income_after_expenses": 0,
    "min_cic_score": 600,
}

# --------------------------- CSS ----------------------------
st.markdown("""
<style>
:root {--navy:#15324B;--blue:#2563EB;--teal:#0F766E;--bg:#F3F7FB;--line:#D9E4EF;}
.stApp {background:linear-gradient(140deg,#F3F7FB 0%,#FFFFFF 55%,#EAF4FF 100%); color:#172B3A;}
.block-container {max-width:1450px;padding-top:1.4rem;padding-bottom:3rem;}
h1,h2,h3 {color:#15324B !important;font-weight:800 !important;}
div[data-testid="stMetric"] {background:#fff;border:1px solid #D9E4EF;border-radius:15px;padding:14px;box-shadow:0 4px 15px #15324B0B;}
div[data-testid="stVerticalBlockBorderWrapper"] {border-color:#D9E4EF !important;border-radius:16px !important;background:#FFFFFF;}
.stButton>button,.stDownloadButton>button {border-radius:10px;font-weight:700;min-height:42px;}
.stButton>button[kind="primary"] {background:#2563EB;color:white;border:0;}
section[data-testid="stSidebar"] {background:linear-gradient(180deg,#15324B,#1E4968);}
section[data-testid="stSidebar"] * {color:white;}
.hero {background:linear-gradient(120deg,#15324B,#2563EB);color:white;padding:25px 28px;border-radius:20px;margin-bottom:20px;box-shadow:0 10px 26px #15324B20;}
.hero h1 {color:white !important;margin:0;font-size:2rem;}
.hero p {color:#E7F0FF;margin:.5rem 0 0 0;}
.small-note {color:#526678;font-size:.9rem;}
.status-good {background:#DCFCE7;color:#166534;padding:8px 12px;border-radius:10px;font-weight:700;}
.status-warn {background:#FEF3C7;color:#92400E;padding:8px 12px;border-radius:10px;font-weight:700;}
.status-bad {background:#FEE2E2;color:#991B1B;padding:8px 12px;border-radius:10px;font-weight:700;}
</style>
""", unsafe_allow_html=True)


# ----------------------- DATA HELPERS -----------------------
def read_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    return default.copy() if isinstance(default, dict) else list(default)


def write_json(path, data):
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp, path)


def load_settings():
    settings = read_json(SETTINGS_FILE, DEFAULT_SETTINGS)
    for key, value in DEFAULT_SETTINGS.items():
        settings.setdefault(key, value)
    return settings


def money(value):
    return f"{value:,.0f} VNĐ".replace(",", ".")


def pct(value):
    return f"{value:.2f}%"


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def monthly_payment(principal, annual_rate_pct, months):
    """Trả góp đều hằng tháng theo dư nợ giảm dần (PMT)."""
    if principal <= 0 or months <= 0:
        return 0.0
    monthly_rate = annual_rate_pct / 100 / 12
    if monthly_rate == 0:
        return principal / months
    return principal * monthly_rate / (1 - (1 + monthly_rate) ** (-months))


def calculate_assessment(data, settings):
    amount = data["loan_amount"]
    months = data["term_months"]
    rate = data["annual_rate"]
    income = data["monthly_income"]
    other_debt = data["existing_monthly_debt"]
    dependents = data["dependents"]
    living_per_dependent = data["living_cost_per_dependent"]
    other_expenses = data["other_monthly_expenses"]
    collateral = data["collateral_value"]

    payment = monthly_payment(amount, rate, months)
    estimated_interest = max(payment * months - amount, 0)
    household_cost = dependents * living_per_dependent
    total_monthly_obligations = other_debt + payment
    dti = (total_monthly_obligations / income * 100) if income > 0 else 999.0
    ltv = (amount / collateral * 100) if collateral > 0 else (0 if amount == 0 else 999.0)
    disposable = income - other_debt - payment - household_cost - other_expenses

    flags = []
    if income <= 0:
        flags.append("Thu nhập tháng phải lớn hơn 0.")
    if dti > settings["max_dti"]:
        flags.append(f"DTI {pct(dti)} vượt ngưỡng tham khảo {pct(settings['max_dti'])}.")
    if collateral <= 0:
        flags.append("Chưa có giá trị tài sản bảo đảm hợp lệ.")
    elif ltv > settings["max_ltv"]:
        flags.append(f"LAV/LTV {pct(ltv)} vượt ngưỡng tham khảo {pct(settings['max_ltv'])}.")
    if disposable < settings["min_income_after_expenses"]:
        flags.append("Dòng tiền còn lại sau chi phí thấp hơn ngưỡng cấu hình.")
    if data["cic_status"] in ("Nợ xấu hiện hữu", "Có nợ nhóm 3–5 trong lịch sử"):
        flags.append("CIC có thông tin bất lợi; cần xác minh theo quy định và chính sách tổ chức.")
    if data["cic_score"] < settings["min_cic_score"]:
        flags.append(f"Điểm CIC thấp hơn ngưỡng tham khảo {settings['min_cic_score']} (nếu thang điểm áp dụng).")
    if data["employment_status"] == "Chưa ổn định":
        flags.append("Nguồn thu nhập/công việc chưa ổn định, cần kiểm tra thêm.")

    hard_concerns = (
        income <= 0
        or dti > settings["max_dti"]
        or collateral <= 0
        or ltv > settings["max_ltv"]
        or data["cic_status"] in ("Nợ xấu hiện hữu", "Có nợ nhóm 3–5 trong lịch sử")
    )
    if hard_concerns:
        recommendation = "CẦN XEM XÉT / BỔ SUNG HỒ SƠ"
        status_type = "bad"
    elif flags or disposable < 0:
        recommendation = "THẨM ĐỊNH BỔ SUNG"
        status_type = "warn"
    else:
        recommendation = "CÓ THỂ CHUYỂN SANG THẨM ĐỊNH CHÍNH THỨC"
        status_type = "good"

    return {
        "monthly_payment": payment,
        "estimated_total_payment": payment * months,
        "estimated_interest": estimated_interest,
        "household_cost": household_cost,
        "total_monthly_obligations": total_monthly_obligations,
        "dti": dti,
        "ltv": ltv,
        "disposable_income": disposable,
        "recommendation": recommendation,
        "status_type": status_type,
        "flags": flags,
    }


def build_record(data, result):
    return {
        "application_id": "LN" + datetime.now().strftime("%Y%m%d%H%M%S%f"),
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        **data,
        "monthly_payment": round(result["monthly_payment"], 2),
        "dti": round(result["dti"], 2),
        "ltv": round(result["ltv"], 2),
        "disposable_income": round(result["disposable_income"], 2),
        "estimated_interest": round(result["estimated_interest"], 2),
        "recommendation": result["recommendation"],
        "flags": result["flags"],
    }


def save_application(record):
    history = read_json(HISTORY_FILE, [])
    history.insert(0, record)
    write_json(HISTORY_FILE, history)


def fmt_or_na(value):
    return "Chưa nhập" if value in (None, "") else str(value)


# -------------------------- HEADER --------------------------
st.markdown("""
<div class="hero">
  <h1>🏦 LoanCheck — Thẩm định cho vay cá nhân</h1>
  <p>Phân tích khả năng trả nợ • DTI • LAV/LTV • CIC • Tài sản bảo đảm</p>
</div>
""", unsafe_allow_html=True)

st.warning(
    "Lưu ý: Đây là công cụ hỗ trợ tính toán và sàng lọc sơ bộ. Kết quả không phải quyết định cấp tín dụng, "
    "không thay thế việc xác minh hồ sơ, chấm điểm theo chính sách nội bộ, định giá TSĐB và phê duyệt của tổ chức cho vay."
)

settings = load_settings()
if "admin_logged_in" not in st.session_state:
    st.session_state.admin_logged_in = False

# --------------------------- SIDEBAR ------------------------
st.sidebar.title("📚 MENU CHỨC NĂNG")
menu_options = ["📝 Hồ sơ & thẩm định", "📖 Giải thích chỉ tiêu"]
if st.session_state.admin_logged_in:
    menu_options += ["🗂️ Lịch sử hồ sơ (Admin)", "⚙️ Cấu hình ngưỡng (Admin)"]
    st.sidebar.success("Đã đăng nhập Admin")
else:
    menu_options += ["🔐 Đăng nhập Admin"]
menu = st.sidebar.radio("Điều hướng", menu_options)
if st.session_state.admin_logged_in and st.sidebar.button("🚪 Đăng xuất"):
    st.session_state.admin_logged_in = False
    st.rerun()

# --------------------- FORM & CALCULATIONS ------------------
if menu == "📝 Hồ sơ & thẩm định":
    st.subheader("1. Thông tin khách hàng và khoản vay")
    with st.form("loan_form", clear_on_submit=False):
        a, b, c = st.columns(3)
        with a:
            customer_name = st.text_input("Họ và tên khách hàng *")
            customer_id = st.text_input("Mã hồ sơ / mã khách hàng")
            age = st.number_input("Tuổi", min_value=18, max_value=100, value=30, step=1)
            marital_status = st.selectbox("Tình trạng hôn nhân", ["Chưa kết hôn", "Đã kết hôn", "Khác / chưa xác định"])
        with b:
            employment_status = st.selectbox("Tình trạng việc làm", ["Ổn định", "Hợp đồng có thời hạn", "Tự kinh doanh", "Chưa ổn định", "Khác"])
            work_years = st.number_input("Số năm làm việc/kinh doanh", min_value=0.0, max_value=70.0, value=2.0, step=0.5)
            monthly_income = st.number_input("Tổng thu nhập ròng/tháng (VNĐ) *", min_value=0, value=20000000, step=1000000)
            other_monthly_expenses = st.number_input("Chi phí cố định khác/tháng (VNĐ)", min_value=0, value=2000000, step=500000)
        with c:
            dependents = st.number_input("Số người phụ thuộc", min_value=0, max_value=30, value=1, step=1)
            living_cost_per_dependent = st.number_input("Chi phí ước tính/người phụ thuộc/tháng (VNĐ)", min_value=0, value=2000000, step=250000)
            existing_monthly_debt = st.number_input("Tổng tiền trả nợ khoản vay cũ/tháng (VNĐ) *", min_value=0, value=2000000, step=500000)
            other_debt_balance = st.number_input("Dư nợ gốc khoản vay cũ (VNĐ)", min_value=0, value=30000000, step=1000000)

        st.divider()
        st.subheader("2. Thông tin khoản vay đề nghị")
        d, e, f = st.columns(3)
        with d:
            loan_amount = st.number_input("Số tiền vay đề nghị (VNĐ) *", min_value=0, value=100000000, step=5000000)
            term_years = st.number_input("Thời hạn vay (năm) *", min_value=1, max_value=40, value=5, step=1)
        with e:
            annual_rate = st.number_input("Lãi suất cho vay (%/năm) *", min_value=0.0, max_value=100.0, value=12.0, step=0.25, format="%.2f")
            purpose = st.selectbox("Mục đích vay", ["Mua nhà/đất", "Mua xe", "Tiêu dùng", "Kinh doanh", "Sửa chữa nhà", "Học tập/y tế", "Khác"])
        with f:
            repayment_method = st.selectbox("Phương thức trả nợ (ước tính)", ["Trả góp đều hằng tháng"])
            other_income = st.number_input("Thu nhập bổ sung/tháng (nếu chưa tính ở trên) (VNĐ)", min_value=0, value=0, step=500000)

        st.divider()
        st.subheader("3. Tài sản bảo đảm và CIC")
        g, h, i = st.columns(3)
        with g:
            collateral_type = st.selectbox("Loại TSĐB", ["Bất động sản", "Ô tô/xe", "Tiền gửi/giấy tờ có giá", "Tài sản khác", "Không có TSĐB"])
            collateral_value = st.number_input("Giá trị TSĐB ước tính (VNĐ) *", min_value=0, value=150000000, step=5000000)
            collateral_legal = st.selectbox("Tình trạng pháp lý TSĐB", ["Đầy đủ/chờ xác minh", "Cần bổ sung hồ sơ", "Có tranh chấp/vướng mắc", "Không áp dụng"])
        with h:
            cic_status = st.selectbox("Kết quả CIC / lịch sử tín dụng", [
                "Tốt / không ghi nhận nợ xấu",
                "Chưa tra cứu CIC",
                "Có nợ nhóm 2 / chậm trả cần xác minh",
                "Có nợ xấu hiện hữu",
                "Có nợ nhóm 3–5 trong lịch sử",
            ])
            cic_score = st.number_input("Điểm CIC (nếu có)", min_value=0, max_value=1000, value=700, step=10)
            cic_checked_date = st.date_input("Ngày tra cứu CIC")
        with i:
            loan_to_value_note = st.caption("LAV/LTV được tính sơ bộ = Số tiền vay / Giá trị TSĐB × 100%. Cần dùng giá trị TSĐB đã được định giá hợp lệ theo quy định.")
            collateral_owner = st.selectbox("Chủ sở hữu TSĐB", ["Chính khách hàng", "Vợ/chồng hoặc người thân", "Bên thứ ba", "Chưa xác minh"])
            notes = st.text_area("Ghi chú thẩm định / hồ sơ cần bổ sung", height=110)

        submitted = st.form_submit_button("🔎 TÍNH TOÁN & THẨM ĐỊNH SƠ BỘ", type="primary", use_container_width=True)

    if submitted:
        if not customer_name.strip():
            st.error("Vui lòng nhập họ tên khách hàng.")
        elif loan_amount <= 0 or monthly_income + other_income <= 0:
            st.error("Số tiền vay phải lớn hơn 0 và thu nhập tháng phải lớn hơn 0.")
        elif collateral_type != "Không có TSĐB" and collateral_value <= 0:
            st.error("Vui lòng nhập giá trị TSĐB lớn hơn 0 hoặc chọn 'Không có TSĐB'.")
        else:
            data = {
                "customer_name": customer_name.strip(),
                "customer_id": customer_id.strip(),
                "age": int(age),
                "marital_status": marital_status,
                "employment_status": employment_status,
                "work_years": float(work_years),
                "monthly_income": float(monthly_income + other_income),
                "base_monthly_income": float(monthly_income),
                "other_income": float(other_income),
                "other_monthly_expenses": float(other_monthly_expenses),
                "dependents": int(dependents),
                "living_cost_per_dependent": float(living_cost_per_dependent),
                "existing_monthly_debt": float(existing_monthly_debt),
                "other_debt_balance": float(other_debt_balance),
                "loan_amount": float(loan_amount),
                "term_years": int(term_years),
                "term_months": int(term_years * 12),
                "annual_rate": float(annual_rate),
                "purpose": purpose,
                "repayment_method": repayment_method,
                "collateral_type": collateral_type,
                "collateral_value": float(collateral_value),
                "collateral_legal": collateral_legal,
                "collateral_owner": collateral_owner,
                "cic_status": cic_status,
                "cic_score": int(cic_score),
                "cic_checked_date": str(cic_checked_date),
                "notes": notes.strip(),
            }
            # Nếu chọn không có TSĐB, giá trị TSĐB được đưa về 0 để tránh tính LTV sai.
            if collateral_type == "Không có TSĐB":
                data["collateral_value"] = 0.0
            result = calculate_assessment(data, settings)
            record = build_record(data, result)
            st.session_state["latest_loan_data"] = data
            st.session_state["latest_loan_result"] = result
            st.session_state["latest_loan_record"] = record

    if "latest_loan_result" in st.session_state:
        data = st.session_state["latest_loan_data"]
        result = st.session_state["latest_loan_result"]
        record = st.session_state["latest_loan_record"]

        st.divider()
        st.subheader("4. Kết quả phân tích sơ bộ")
        css_class = {"good": "status-good", "warn": "status-warn", "bad": "status-bad"}[result["status_type"]]
        st.markdown(f'<div class="{css_class}">KẾT LUẬN GỢI Ý: {result["recommendation"]}</div>', unsafe_allow_html=True)
        st.caption("Đây là gợi ý theo các ngưỡng tham khảo đang cấu hình, không phải quyết định cho vay.")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Khoản trả hằng tháng", money(result["monthly_payment"]))
        m2.metric("DTI", pct(result["dti"]), help="(Khoản nợ cũ phải trả/tháng + khoản trả mới/tháng) / tổng thu nhập ròng/tháng.")
        m3.metric("LAV / LTV", pct(result["ltv"]), help="Số tiền vay / giá trị TSĐB × 100%.")
        m4.metric("Dòng tiền còn lại", money(result["disposable_income"]))

        m5, m6, m7 = st.columns(3)
        m5.metric("Tổng trả dự kiến", money(result["estimated_total_payment"]))
        m6.metric("Lãi dự kiến toàn kỳ", money(result["estimated_interest"]))
        m7.metric("Chi phí người phụ thuộc", money(result["household_cost"]))

        with st.expander("📐 Công thức và dữ liệu tính toán", expanded=True):
            st.markdown(f"""
- **Thu nhập ròng dùng để tính:** {money(data['monthly_income'])}/tháng (đã cộng thu nhập bổ sung).
- **Nợ phải trả mỗi tháng:** {money(data['existing_monthly_debt'])} nợ cũ + {money(result['monthly_payment'])} khoản vay mới = **{money(result['total_monthly_obligations'])}**.
- **DTI:** ({money(data['existing_monthly_debt'])} + {money(result['monthly_payment'])}) / {money(data['monthly_income'])} × 100 = **{pct(result['dti'])}**.
- **LAV/LTV:** {money(data['loan_amount'])} / {money(data['collateral_value']) if data['collateral_value'] > 0 else '0 VNĐ (không có TSĐB)'} × 100 = **{pct(result['ltv'])}**.
- **Dòng tiền còn lại:** Thu nhập − nợ cũ − khoản trả mới − chi phí người phụ thuộc − chi phí cố định khác = **{money(result['disposable_income'])}**.
- **Lãi ước tính:** tổng khoản trả theo công thức trả góp đều trừ số tiền gốc; chưa tính phí, bảo hiểm, thay đổi lãi suất hoặc cách tính thực tế của bên cho vay.
            """)
        if result["flags"]:
            st.markdown("#### ⚠️ Các điểm cần rà soát")
            for flag in result["flags"]:
                st.warning(flag)
        else:
            st.success("Chưa phát hiện cảnh báo theo các ngưỡng sơ bộ đã cấu hình. Vẫn cần xác minh hồ sơ và nguồn dữ liệu.")

        extra_flags = []
        if data["collateral_legal"] in ("Có tranh chấp/vướng mắc", "Cần bổ sung hồ sơ"):
            extra_flags.append("Tình trạng pháp lý TSĐB cần được kiểm tra/hoàn thiện.")
        if data["collateral_owner"] in ("Bên thứ ba", "Chưa xác minh"):
            extra_flags.append("Cần xác minh quyền sở hữu và sự đồng ý hợp lệ của chủ TSĐB.")
        if data["cic_status"] == "Chưa tra cứu CIC":
            extra_flags.append("Chưa có kết quả CIC xác thực tại thời điểm thẩm định.")
        for flag in extra_flags:
            st.warning(flag)

        st.markdown("#### 📄 Lưu hồ sơ")
        st.caption("Chỉ lưu vào tệp JSON khi nhấn nút dưới đây. Dữ liệu được lưu trên môi trường chạy ứng dụng.")
        col_save, col_json, col_csv = st.columns(3)
        with col_save:
            if st.button("💾 Lưu hồ sơ thẩm định", type="primary", use_container_width=True):
                if "saved_application_id" not in st.session_state or st.session_state.saved_application_id != record["application_id"]:
                    save_application(record)
                    st.session_state.saved_application_id = record["application_id"]
                    st.success(f"Đã lưu hồ sơ {record['application_id']}.")
                else:
                    st.info("Hồ sơ này đã được lưu, không tạo bản ghi trùng.")
        with col_json:
            st.download_button("⬇️ Tải báo cáo JSON", data=json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8"),
                               file_name=f"{record['application_id']}.json", mime="application/json", use_container_width=True)
        with col_csv:
            report_df = pd.DataFrame([{
                "Mã hồ sơ": record["application_id"], "Khách hàng": data["customer_name"],
                "Số tiền vay": data["loan_amount"], "Kỳ hạn (tháng)": data["term_months"],
                "Lãi suất (%/năm)": data["annual_rate"], "Trả/tháng": result["monthly_payment"],
                "Thu nhập/tháng": data["monthly_income"], "DTI (%)": result["dti"],
                "TSĐB": data["collateral_value"], "LAV/LTV (%)": result["ltv"],
                "CIC": data["cic_status"], "Gợi ý": result["recommendation"],
            }])
            st.download_button("⬇️ Tải báo cáo CSV", data=report_df.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"{record['application_id']}.csv", mime="text/csv", use_container_width=True)

elif menu == "📖 Giải thích chỉ tiêu":
    st.subheader("Giải thích các chỉ tiêu chính")
    with st.container(border=True):
        st.markdown("### DTI — Debt-to-Income")
        st.latex(r"DTI = \\frac{Nợ\\ phải\\ trả\\ hằng\\ tháng}{Thu\\ nhập\\ ròng\\ hằng\\ tháng}\\times100\\%")
        st.write("Trong ứng dụng, DTI = (tiền trả khoản vay cũ/tháng + khoản trả khoản vay mới/tháng) / tổng thu nhập ròng/tháng. Tổ chức cho vay có thể định nghĩa DTI khác nhau.")
    with st.container(border=True):
        st.markdown("### LAV/LTV — Tỷ lệ khoản vay trên giá trị tài sản bảo đảm")
        st.latex(r"LTV = \\frac{Số\\ tiền\\ vay}{Giá\\ trị\\ TSĐB}\\times100\\%")
        st.write("Tài sản phải được định giá, kiểm tra pháp lý và áp dụng tỷ lệ cho vay theo loại tài sản/chính sách của tổ chức. Không dùng giá tự khai làm kết quả định giá chính thức.")
    with st.container(border=True):
        st.markdown("### Khả năng trả nợ")
        st.write("Khoản trả hằng tháng được ước tính theo công thức trả góp đều trên dư nợ, dùng lãi suất năm chia 12. Dòng tiền còn lại = thu nhập − nợ cũ − khoản trả mới − chi phí người phụ thuộc − chi phí cố định khác.")
    with st.container(border=True):
        st.markdown("### CIC")
        st.write("CIC là một nguồn thông tin lịch sử tín dụng cần được tra cứu hợp lệ và đối chiếu hồ sơ. Không nên tự kết luận cấp tín dụng chỉ dựa vào một điểm số; trạng thái nợ, độ mới của dữ liệu, sai lệch dữ liệu và chính sách hiện hành đều cần được kiểm tra.")
    st.info("Các ngưỡng DTI/LTV/điểm CIC trong app là ngưỡng tham khảo có thể chỉnh trong phần Admin. Không có một ngưỡng duy nhất phù hợp cho mọi ngân hàng, sản phẩm và loại tài sản.")

elif menu == "🔐 Đăng nhập Admin":
    st.subheader("🔐 Đăng nhập quản trị")
    st.write("Tài khoản mặc định lần chạy đầu: `admin` / `123456`. Hãy đổi mật khẩu ngay trong phần cấu hình Admin sau khi đăng nhập.")
    with st.form("admin_login"):
        username = st.text_input("Tên đăng nhập")
        password = st.text_input("Mật khẩu", type="password")
        login = st.form_submit_button("Đăng nhập", type="primary")
    if login:
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        if username == settings["admin_username"] and password_hash == settings["admin_password_hash"]:
            st.session_state.admin_logged_in = True
            st.success("Đăng nhập thành công.")
            st.rerun()
        else:
            st.error("Tên đăng nhập hoặc mật khẩu không đúng.")

elif menu == "🗂️ Lịch sử hồ sơ (Admin)":
    st.subheader("🗂️ Lịch sử hồ sơ thẩm định")
    history = read_json(HISTORY_FILE, [])
    if not history:
        st.info("Chưa có hồ sơ nào được lưu.")
    else:
        df = pd.DataFrame([{
            "Mã hồ sơ": x.get("application_id"),
            "Thời gian": x.get("created_at"),
            "Khách hàng": x.get("customer_name"),
            "Số tiền vay": x.get("loan_amount"),
            "Kỳ hạn (tháng)": x.get("term_months"),
            "Trả/tháng": x.get("monthly_payment"),
            "DTI (%)": x.get("dti"),
            "LAV/LTV (%)": x.get("ltv"),
            "CIC": x.get("cic_status"),
            "Gợi ý": x.get("recommendation"),
        } for x in history])
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Tải toàn bộ lịch sử CSV", data=df.to_csv(index=False).encode("utf-8-sig"),
                           file_name="lich_su_tham_dinh_vay.csv", mime="text/csv")
        st.download_button("⬇️ Sao lưu dữ liệu JSON", data=json.dumps(history, ensure_ascii=False, indent=2).encode("utf-8"),
                           file_name="loan_applications_backup.json", mime="application/json")
        st.divider()
        ids = [x.get("application_id") for x in history]
        selected_id = st.selectbox("Chọn mã hồ sơ để xem chi tiết hoặc xóa", ids)
        selected = next((x for x in history if x.get("application_id") == selected_id), None)
        if selected:
            with st.expander("Xem chi tiết hồ sơ"):
                st.json(selected)
            confirm_delete = st.checkbox("Tôi xác nhận muốn xóa hồ sơ đã chọn", key="confirm_delete")
            if st.button("🗑️ Xóa hồ sơ", disabled=not confirm_delete):
                history = [x for x in history if x.get("application_id") != selected_id]
                write_json(HISTORY_FILE, history)
                st.success("Đã xóa hồ sơ khỏi tệp lịch sử.")
                st.rerun()

elif menu == "⚙️ Cấu hình ngưỡng (Admin)":
    st.subheader("⚙️ Cấu hình ngưỡng tham khảo")
    st.caption("Điều chỉnh theo chính sách đã được tổ chức phê duyệt. Không dùng mặc định dưới đây như quy định pháp lý.")
    with st.form("settings_form"):
        max_dti = st.number_input("DTI tối đa tham khảo (%)", min_value=1.0, max_value=200.0, value=float(settings["max_dti"]), step=1.0)
        max_ltv = st.number_input("LAV/LTV tối đa tham khảo (%)", min_value=1.0, max_value=200.0, value=float(settings["max_ltv"]), step=1.0)
        min_disposable = st.number_input("Dòng tiền còn lại tối thiểu (VNĐ/tháng)", min_value=0, value=int(settings["min_income_after_expenses"]), step=500000)
        min_cic_score = st.number_input("Điểm CIC tối thiểu tham khảo", min_value=0, max_value=1000, value=int(settings["min_cic_score"]), step=10)
        st.divider()
        st.markdown("#### Đổi tài khoản quản trị")
        new_username = st.text_input("Tên đăng nhập Admin", value=settings["admin_username"])
        new_password = st.text_input("Mật khẩu Admin mới (để trống nếu không đổi)", type="password")
        save_settings = st.form_submit_button("💾 Lưu cấu hình", type="primary")
    if save_settings:
        settings["max_dti"] = float(max_dti)
        settings["max_ltv"] = float(max_ltv)
        settings["min_income_after_expenses"] = int(min_disposable)
        settings["min_cic_score"] = int(min_cic_score)
        settings["admin_username"] = new_username.strip() or "admin"
        if new_password:
            settings["admin_password_hash"] = hashlib.sha256(new_password.encode()).hexdigest()
        write_json(SETTINGS_FILE, settings)
        st.success("Đã lưu cấu hình.")
        st.rerun()

st.divider()
st.caption("LoanCheck • Phiên bản mẫu phục vụ học tập/thử nghiệm. Dữ liệu hồ sơ là thông tin nhạy cảm: chỉ nhập dữ liệu được phép xử lý, hạn chế quyền truy cập và bảo vệ nơi lưu trữ.")

