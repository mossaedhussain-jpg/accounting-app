import streamlit as st
import pandas as pd
import io
from datetime import datetime
import re

st.set_page_config(page_title="نظام التحليل المحاسبي — مداميك", layout="wide", page_icon="🧾")

st.markdown("""
<style>
[data-testid="stAppViewContainer"] { direction: rtl; }
[data-testid="stSidebar"] { direction: rtl; }
.stTabs [data-baseweb="tab"] { direction: rtl; }
h1,h2,h3 { direction: rtl; text-align: right; }
.metric-card { background: white; border: 1px solid #e9ecef; border-radius: 10px; padding: 16px; text-align: center; }
.prob-severe { border-right: 4px solid #dc3545; background: #fff5f5; border-radius: 8px; padding: 12px; margin: 8px 0; }
.prob-medium { border-right: 4px solid #ffc107; background: #fffdf0; border-radius: 8px; padding: 12px; margin: 8px 0; }
.prob-simple { border-right: 4px solid #0d6efd; background: #f0f7ff; border-radius: 8px; padding: 12px; margin: 8px 0; }
.entry-box { background: #f1f3f5; border-radius: 6px; padding: 8px 12px; font-family: monospace; font-size: 13px; color: #0c4a7c; direction: rtl; margin: 6px 0; }
</style>
""", unsafe_allow_html=True)

# =====================================================
# SMART COLUMN DETECTION
# =====================================================
def detect_columns(df):
    """Detect debit, credit, and account name columns smartly"""
    cols = {c.strip(): c for c in df.columns}
    
    debit_col = None
    credit_col = None
    name_col = None
    
    for c in df.columns:
        cl = str(c).lower().strip()
        if any(k in cl for k in ['مدين','debit','dr','مدين (sar)','مدين (egp)','مدين (جنيه)']):
            debit_col = c
        if any(k in cl for k in ['دائن','credit','cr','دائن (sar)','دائن (egp)','دائن (جنيه)']):
            credit_col = c
        if any(k in cl for k in ['اسم','حساب','account','name','البيان','وصف']):
            name_col = c
    
    # If no name col found, use first text col
    if not name_col:
        for c in df.columns:
            if df[c].dtype == object:
                name_col = c
                break
    
    # If no credit col, look for any numeric col that's not debit
    if not credit_col:
        for c in df.columns:
            if c != debit_col and c != name_col:
                try:
                    pd.to_numeric(df[c].astype(str).str.replace(',',''), errors='raise')
                    credit_col = c
                    break
                except: pass
    
    return name_col, debit_col, credit_col

def safe_num(val):
    try:
        if pd.isna(val): return 0.0
        return float(str(val).replace(',','').replace(' ','') or 0)
    except: return 0.0

def fmt(n):
    return f"{abs(round(n)):,.2f}"

# =====================================================
# ACCOUNTING RULES ENGINE
# =====================================================
def analyze_df(df, name_col, debit_col, credit_col):
    problems = []
    total_d = 0
    total_c = 0
    
    for _, row in df.iterrows():
        name = str(row[name_col]).strip() if name_col and name_col in row else ''
        if not name or name in ['nan','None',''] or name == str(row.name): continue
        
        d = safe_num(row[debit_col]) if debit_col and debit_col in row else 0
        c = safe_num(row[credit_col]) if credit_col and credit_col in row else 0
        bal = d - c
        nl = name.lower()
        
        total_d += d
        total_c += c
        
        # Rules
        if bal < -1 and any(k in nl for k in ['نقد','كاش','صندوق','cash','petty','بنك','bank','راجحي','الاهلي']):
            problems.append({'title':'رصيد حساب نقدي/بنكي سالب','sev':'جوهرية','acc':name,
                'desc':f"حساب '{name}' برصيد سالب ({fmt(bal)}) — مستحيل محاسبياً.",
                'entry':f"مراجعة شاملة لقيود حساب {name}",
                'sol':'تحقق من قيود خاطئة أو مكررة.','app':False})
        
        if bal < -1 and any(k in nl for k in ['مخزون','بضاع','stock','inventory','مخزن']):
            problems.append({'title':'رصيد مخزون سالب','sev':'جوهرية','acc':name,
                'desc':f"مخزون '{name}' برصيد سالب ({fmt(bal)}) — بيع أكثر مما اشتريت.",
                'entry':f"من ح/ مخزون  إلى ح/ فرق جرد  بمبلغ {fmt(abs(bal))}",
                'sol':'تحقق من قيود التوريد — قد يكون توريد لم يُسجَّل.','app':False})
        
        if any(k in nl for k in ['مصروف','مصاريف','تكلفة','expense','cost','رواتب','اجور','أجور']) and c > d + 1 and d >= 0:
            problems.append({'title':'مصروف برصيد دائن','sev':'متوسطة','acc':name,
                'desc':f"حساب مصروف '{name}' برصيد دائن ({fmt(c-d)}) — الطبيعي أن يكون مدين.",
                'entry':f"من ح/ {name}  إلى ح/ مصاريف مستحقة  بمبلغ {fmt(abs(bal))}",
                'sol':'تحقق من ترحيل خاطئ أو استرداد مصروف.','app':False})
        
        if any(k in nl for k in ['إيراد','ايراد','مبيعات','revenue','sales','income']) and d > c + 1:
            problems.append({'title':'إيراد برصيد مدين','sev':'متوسطة','acc':name,
                'desc':f"إيراد '{name}' برصيد مدين ({fmt(d-c)}) — الطبيعي أن يكون دائن.",
                'entry':f"من ح/ أرباح محتجزة  إلى ح/ {name}  بمبلغ {fmt(abs(d-c))}",
                'sol':'تحقق من قيود الإلغاء.','app':False})
        
        if any(k in nl for k in ['ضريبة','vat','tax','زكاة']) and abs(bal) > 100:
            problems.append({'title':'ضريبة/زكاة تحتاج تسوية','sev':'متوسطة','acc':name,
                'desc':f"حساب '{name}' برصيد ({fmt(bal)}) يحتاج تسوية.",
                'entry':f"تسوية حساب الضريبة بمبلغ {fmt(abs(bal))}",
                'sol':'احسب صافي الضريبة وسجّل قيد التسوية.','app':False})
        
        if any(k in nl for k in ['انتظار','مؤقت','suspense','clearing','تسوية']) and abs(bal) > 1000:
            problems.append({'title':'حساب انتظار برصيد كبير','sev':'متوسطة','acc':name,
                'desc':f"حساب '{name}' برصيد ({fmt(bal)}) — يجب إقفاله.",
                'entry':'تحليل المفردات وترحيلها للحسابات الصحيحة',
                'sol':'أقفل كل بند في حسابه الصحيح.','app':False})
        
        if any(k in nl for k in ['مدفوع مقدم','مصروف مقدم','prepaid','مقدمة','دفعة مقدمة']) and bal > 1:
            problems.append({'title':'مصاريف/دفعات مقدمة — تسوية مطلوبة','sev':'بسيطة','acc':name,
                'desc':f"'{name}' برصيد ({fmt(bal)}) — تحقق من الجزء المستهلك.",
                'entry':'من ح/ المصروف المعني  إلى ح/ مدفوع مقدم  بالجزء المستحق',
                'sol':'احسب الجزء المستحق وسجّل قيد التسوية.','app':False})
        
        if any(k in nl for k in ['مخصص','provision','اهلاك مجمع','مجمع اهلاك']) and d > c:
            problems.append({'title':'مخصص/مجمع إهلاك برصيد مدين','sev':'متوسطة','acc':name,
                'desc':f"'{name}' برصيد مدين ({fmt(d-c)}) — الطبيعي دائن.",
                'entry':f"مراجعة قيود الإهلاك لـ {name}",
                'sol':'تحقق من قيود الإهلاك وصحح الأرصدة.','app':False})
        
        if any(k in nl for k in ['إيرادات مستحقة','ايرادات مستحقة','accrued revenue']) and bal < 0:
            problems.append({'title':'إيرادات مستحقة برصيد سالب','sev':'متوسطة','acc':name,
                'desc':f"'{name}' برصيد سالب ({fmt(bal)}) — يحتاج مراجعة.",
                'entry':f"من ح/ إيرادات مستحقة  إلى ح/ الإيراد المعني  بمبلغ {fmt(abs(bal))}",
                'sol':'تحقق من توقيت الاعتراف بالإيراد.','app':False})
    
    # Check overall balance
    diff = abs(total_d - total_c)
    if diff > 1:
        problems.insert(0, {'title':'الميزان غير متوازن','sev':'جوهرية','acc':'الميزان كله',
            'desc':f"إجمالي المدين ({fmt(total_d)}) ≠ إجمالي الدائن ({fmt(total_c)}) — فرق: {fmt(diff)}",
            'entry':'مراجعة شاملة لكل القيود',
            'sol':'ابحث عن القيد المسبب للفرق وصحّحه.','app':False})
    
    return problems, total_d, total_c

# =====================================================
# FINANCIAL STATEMENTS
# =====================================================
def build_statements(df, name_col, debit_col, credit_col):
    fs = {'rev':[],'exp':[],'ac':[],'anc':[],'lc':[],'lnc':[],'eq':[]}
    
    for _, row in df.iterrows():
        name = str(row[name_col]).strip() if name_col else ''
        if not name or name in ['nan','None','']: continue
        
        d = safe_num(row[debit_col]) if debit_col and debit_col in row else 0
        c = safe_num(row[credit_col]) if credit_col and credit_col in row else 0
        bal = abs(d - c)
        if bal < 0.01: continue
        
        nl = name.lower()
        
        if any(k in nl for k in ['مبيعات','إيراد','ايراد','revenue','sales','income','خصم مكتسب','إيرادات أخرى']):
            fs['rev'].append((name, c - d if c > d else bal))
        elif any(k in nl for k in ['مصروف','مصاريف','تكلفة','رواتب','اجور','أجور','expense','cost','ايجار','كهرباء','ديزل','وقود','مقاولة من الباطن','اهلاك','إهلاك','نثريات','مخالفات','ضيافة','تذاكر','تامين','رسوم','سجل','استشارات','خدمات','منصة','مصنعيات','ردميات','يوميات','مواد','صيانة']):
            fs['exp'].append((name, bal))
        elif any(k in nl for k in ['نقد','بنك','راجحي','الاهلي','cash','bank','عميل','مخزون','مخزن','ذمم مدينة','receivable','inventory','prepaid','مقدم','عهدة','دفعة مقدمة','إيرادات مستحقة']):
            fs['ac'].append((name, bal))
        elif any(k in nl for k in ['أصل ثابت','عقار','آلات','معدات','fixed','property','equipment','أراضي','سيارة','لابتوب','مكيف','قصاصة','جي سي بي']):
            fs['anc'].append((name, bal))
        elif any(k in nl for k in ['دائن','موردون','قرض قصير','payable','supplier','مؤسسة','شركة','مورد','فواتير لم تصل','مصروفات مستحقة','ضريبة القيمة']):
            fs['lc'].append((name, bal))
        elif any(k in nl for k in ['قرض طويل','سند','long','bond','مخصص مكافأة','مخصص مكافاة']):
            fs['lnc'].append((name, bal))
        elif any(k in nl for k in ['رأس المال','رأس مال','capital','أرباح','retained','equity','احتياطي','جاري الشريك','إعادة تقييم']):
            fs['eq'].append((name, bal))
    
    return fs

# =====================================================
# UI
# =====================================================
with st.sidebar:
    st.markdown("## 🧾 نظام المحاسبة")
    st.markdown("---")
    standard = st.radio("المعيار المحاسبي", ["EAS — المعايير المصرية", "IFRS"], index=0)
    std = standard.split("—")[0].strip()
    st.markdown("---")
    st.caption(f"تاريخ اليوم: {datetime.now().strftime('%Y-%m-%d')}")

st.title("نظام التحليل المحاسبي الذكي")
st.caption(f"وفق معايير {std}")

tab1, tab2, tab3, tab4 = st.tabs(["📂 رفع الميزان", "⚠️ المشاكل والتسويات", "📊 قائمة الدخل", "🏦 الميزانية العمومية"])

with tab1:
    uploaded = st.file_uploader("ارفع ملف ميزان المراجعة", type=['xlsx','xls','csv'])
    
    if uploaded:
        try:
            if uploaded.name.endswith('.csv'):
                df = pd.read_csv(uploaded, encoding='utf-8-sig', on_bad_lines='skip')
            elif uploaded.name.endswith('.xls'):
                df = pd.read_excel(uploaded, engine='xlrd')
            else:
                df = pd.read_excel(uploaded)
            
            df.columns = [str(c).strip() for c in df.columns]
            # Remove completely empty rows
            df = df.dropna(how='all')
            
            name_col, debit_col, credit_col = detect_columns(df)
            
            st.success(f"✓ تم رفع الملف — {len(df)} سطر")
            
            col1, col2, col3 = st.columns(3)
            col1.info(f"عمود الاسم: **{name_col}**")
            col2.info(f"عمود المدين: **{debit_col}**")
            col3.info(f"عمود الدائن: **{credit_col if credit_col else 'غير موجود'}**")
            
            st.dataframe(df.head(15), use_container_width=True)
            
            if st.button("🔍 تحليل الميزان", type="primary", use_container_width=True):
                with st.spinner("جاري التحليل..."):
                    problems, td, tc = analyze_df(df, name_col, debit_col, credit_col)
                    fs = build_statements(df, name_col, debit_col, credit_col)
                    st.session_state['problems'] = problems
                    st.session_state['fs'] = fs
                    st.session_state['td'] = td
                    st.session_state['tc'] = tc
                    st.session_state['df'] = df
                    st.session_state['cols'] = (name_col, debit_col, credit_col)
                
                st.success(f"✓ اكتمل التحليل — {len(problems)} مشكلة مكتشفة")
                
                c1,c2,c3,c4 = st.columns(4)
                c1.metric("إجمالي المدين", f"{td:,.0f}")
                c2.metric("إجمالي الدائن", f"{tc:,.0f}")
                c3.metric("الفرق", f"{abs(td-tc):,.0f}")
                c4.metric("حالة الميزان", "متوازن ✓" if abs(td-tc)<1 else "غير متوازن ✗")
                
                st.info("انتقل للتبويبات الأخرى لمشاهدة النتائج")
        
        except Exception as e:
            st.error(f"خطأ: {e}")
            st.info("إذا كان الملف .xls قديم، حوّله إلى .xlsx وأعد الرفع")

with tab2:
    if 'problems' not in st.session_state:
        st.info("ارفع وحلّل الميزان أولاً")
    else:
        probs = st.session_state['problems']
        sev = sum(1 for p in probs if p['sev']=='جوهرية')
        mid = sum(1 for p in probs if p['sev']=='متوسطة')
        sim = sum(1 for p in probs if p['sev']=='بسيطة')
        
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("إجمالي المشاكل", len(probs))
        c2.metric("🔴 جوهرية", sev)
        c3.metric("🟡 متوسطة", mid)
        c4.metric("🔵 بسيطة", sim)
        
        st.divider()
        
        if not probs:
            st.success("✅ لم تُكتشف مشاكل في الميزان — الميزان سليم")
        else:
            icons = {'جوهرية':'🔴','متوسطة':'🟡','بسيطة':'🔵'}
            for i, p in enumerate(probs):
                with st.expander(f"{icons.get(p['sev'],'')} {p['title']} — {p['acc'][:50]}", expanded=(p['sev']=='جوهرية')):
                    st.write(p['desc'])
                    st.markdown(f"<div class='entry-box'>📌 القيد المقترح: {p['entry']}</div>", unsafe_allow_html=True)
                    st.caption(f"💡 الحل: {p['sol']}")
                    col_a, col_b, col_c = st.columns([1,1,4])
                    if col_a.button("✓ تطبيق", key=f"ap_{i}"):
                        st.session_state['problems'][i]['app'] = True
                        st.success("تمت الموافقة على التسوية")
                    if col_b.button("تجاهل", key=f"sk_{i}"):
                        st.session_state['problems'][i]['app'] = False
                        st.info("تم التجاهل")

def stmt_section(title, items):
    if not items:
        st.caption(f"*لا توجد بنود في {title}*")
        return 0
    total = 0
    st.markdown(f"**{title}**")
    for name, amt in items:
        col1, col2 = st.columns([4,1])
        col1.write(name[:60])
        col2.write(f"{amt:,.2f}")
        total += amt
    st.markdown(f"**الإجمالي: {total:,.2f}**")
    st.divider()
    return total

with tab3:
    if 'fs' not in st.session_state:
        st.info("ارفع وحلّل الميزان أولاً")
    else:
        fs = st.session_state['fs']
        st.subheader(f"قائمة الدخل — وفق معايير {std}")
        st.caption(f"للفترة المنتهية في: {datetime.now().strftime('%Y-%m-%d')}")
        st.divider()
        
        tr = stmt_section("الإيرادات", fs['rev'])
        te = stmt_section("المصروفات والتكاليف", fs['exp'])
        net = tr - te
        
        if net >= 0:
            st.success(f"### صافي الربح: {net:,.2f} SAR")
        else:
            st.error(f"### صافي الخسارة: ({abs(net):,.2f}) SAR")
        
        # Export
        st.divider()
        buf = io.BytesIO()
        rows = []
        for n,v in fs['rev']: rows.append(('إيرادات', n, v))
        for n,v in fs['exp']: rows.append(('مصروفات', n, v))
        rows.append(('النتيجة', 'صافي الربح/الخسارة', net))
        pd.DataFrame(rows, columns=['القسم','البند','المبلغ']).to_excel(buf, index=False)
        st.download_button("💾 تحميل قائمة الدخل", buf.getvalue(), "قائمة_الدخل.xlsx")

with tab4:
    if 'fs' not in st.session_state:
        st.info("ارفع وحلّل الميزان أولاً")
    else:
        fs = st.session_state['fs']
        st.subheader(f"الميزانية العمومية — وفق معايير {std}")
        st.caption(f"كما في: {datetime.now().strftime('%Y-%m-%d')}")
        st.divider()
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### الأصول")
            ta_c = stmt_section("أصول متداولة", fs['ac'])
            ta_nc = stmt_section("أصول غير متداولة", fs['anc'])
            st.success(f"**إجمالي الأصول: {ta_c+ta_nc:,.2f}**")
        
        with col2:
            st.markdown("### الالتزامات وحقوق الملكية")
            tl_c = stmt_section("التزامات متداولة", fs['lc'])
            tl_nc = stmt_section("التزامات غير متداولة", fs['lnc'])
            te_eq = stmt_section("حقوق الملكية", fs['eq'])
            st.success(f"**الإجمالي: {tl_c+tl_nc+te_eq:,.2f}**")
        
        # Export
        st.divider()
        buf2 = io.BytesIO()
        rows2 = []
        for n,v in fs['ac']: rows2.append(('أصول متداولة',n,v))
        for n,v in fs['anc']: rows2.append(('أصول غير متداولة',n,v))
        for n,v in fs['lc']: rows2.append(('التزامات متداولة',n,v))
        for n,v in fs['lnc']: rows2.append(('التزامات غير متداولة',n,v))
        for n,v in fs['eq']: rows2.append(('حقوق الملكية',n,v))
        pd.DataFrame(rows2, columns=['القسم','البند','المبلغ']).to_excel(buf2, index=False)
        st.download_button("💾 تحميل الميزانية", buf2.getvalue(), "الميزانية_العمومية.xlsx")
