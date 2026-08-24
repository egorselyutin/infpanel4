import streamlit as st
import pandas as pd
import os
import io
import json
import base64
import sqlite3
import html
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
from svgpathtools import parse_path

# =============================================================================
# 0. ПОДКЛЮЧЕНИЕ ШРИФТОВ GOLOS
# =============================================================================
font_faces_css = """
@font-face {
  font-family: 'Golos UI';
  src: url('/static/fonts/Golos-UI_VF.woff2') format('woff2'),
       url('/static/fonts/Golos-UI_VF.woff') format('woff');
  font-weight: 100 900;
  font-style: normal;
  font-display: swap;
}
@font-face {
  font-family: 'Golos Text';
  src: url('/static/fonts/golos-text_vf.woff2') format('woff2'),
       url('/static/fonts/golos-text_vf.woff') format('woff');
  font-weight: 100 900;
  font-style: normal;
  font-display: swap;
}
"""

# =============================================================================
# 1. ИНИЦИАЛИЗАЦИЯ ХРАНИЛИЩА И СЧЕТЧИКА ПОСЕЩЕНИЙ
# =============================================================================
def init_counter_db():
    conn = sqlite3.connect('visits.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS counter (id INTEGER PRIMARY KEY, count INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS processed_sessions (session_key TEXT PRIMARY KEY)''')
    cursor.execute('SELECT count FROM counter WHERE id = 1')
    if cursor.fetchone() is None:
        cursor.execute('INSERT INTO counter (id, count) VALUES (1, 0)')
    conn.commit()
    conn.close()

def increment_and_get_visits(current_session_key):
    conn = sqlite3.connect('visits.db')
    cursor = conn.cursor()
    cursor.execute('SELECT session_key FROM processed_sessions WHERE session_key = ?', (current_session_key,))
    if cursor.fetchone() is None:
        cursor.execute('INSERT INTO processed_sessions (session_key) VALUES (?)', (current_session_key,))
        cursor.execute('UPDATE counter SET count = count + 1 WHERE id = 1')
        conn.commit()
    cursor.execute('SELECT count FROM counter WHERE id = 1')
    count = cursor.fetchone()[0]
    conn.close()
    return count

init_counter_db()

# =============================================================================
# 2. НАСТРОЙКА СТРАНИЦЫ И ГЛОБАЛЬНОЙ СЕССИИ
# =============================================================================
st.set_page_config(page_title="Информационный портал КФД НСО", layout="wide", page_icon="🏦")

try:
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    ctx = get_script_run_ctx()
    session_id = ctx.session_id if ctx else "default_session"
except Exception:
    session_id = "fallback_session"

def set_date_param():
    if "selected_date" in st.session_state:
        st.query_params["date"] = st.session_state.selected_date

query_params = st.query_params
has_region_param = "region" in query_params
show_contacts = query_params.get("show_contacts", "") == "1"

current_date = query_params.get("date", "01.07.2025")
if isinstance(current_date, list):
    current_date = current_date[0]

if 'visit_counted' not in st.session_state:
    if not has_region_param:
        st.session_state.visit_count = increment_and_get_visits(session_id)
    else:
        conn = sqlite3.connect('visits.db')
        cursor = conn.cursor()
        cursor.execute('SELECT count FROM counter WHERE id = 1')
        res = cursor.fetchone()
        st.session_state.visit_count = res[0] if res else 0
        conn.close()
    st.session_state.visit_counted = True

# =============================================================================
# 3. НАСТРОЙКА СПИСКА РАЙОНОВ С ТЕМНЫМ ШРИФТОМ НА КАРТАХ
# =============================================================================
# DARK_FONT_REGIONS = ["Краснозерский", "Татарский"]

# Константы
# цвет шрифта пилотного района
DARK_FONT_REGION_COLOR = "#02bd34"

# Колонки таблицы населенных пунктов (npTable), которые на странице района
# отображаются в виде переключателя "да/нет" со стрелочками вверх-вниз
# вместо числового значения. При переключении значения в npTable
# автоматически пересчитывается суммарное количество "да" в соответствующей
# колонке таблицы района (districtTable).
TOGGLE_YES_NO_COLUMNS = [
    "Количество точек финансового доступа",
    "Количество Финансовых помощников",
    "Количество торговых точек с сервисом \"Выдача наличных на кассе\"",
]

# =============================================================================
# 4. ОПТИМИЗИРОВАННЫЕ ФУНКЦИИ ДАННЫХ
# =============================================================================

# Загрузка конфигурации (раздел инициализации данных)
@st.cache_data
def load_config(file_path="config.json"):
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

# Загружаем конфиг
config = load_config()

# Получаем список дат для выбора (отсортированный)
dates_list = list(config.get("reporting_dates", {}).keys())

# Получаем список регионов для выбранной даты
selected_config = config.get("reporting_dates", {}).get(current_date, {})
DARK_FONT_REGIONS = selected_config.get("dark_font_regions", [])

# Функция мониторинга/автозамены "переноса строки" Alt Enter на перенос строки при отображении
def process_excel_linebreaks(df):
  # Проходим по всем колонкам и заменяем реальные символы переноса на HTML-тег <br>
  for col in df.select_dtypes(include=["object", "string"]).columns:
    df[col] = (
        df[col]
        .astype(str)
        .str.replace("\r\n", "<br>", regex=False)
        .str.replace("\n", "<br>", regex=False)
    )
  return df

def short_region_name(name):
    name = str(name)
    for rep in [" муниципальный район", " городской округ", " муниципальный округ", " район"]:
        name = name.replace(rep, "")
    return name.strip()

def get_need_level_class(col_name, num_val):
    if not str(col_name).startswith("Уровень потребности в ДБО"):
        return ""
    num_val = round(num_val, 2)
    if 0 <= num_val < 11:
        return "need-level-0-10"
    elif 11 <= num_val < 16:
        return "need-level-11-15"
    elif 16 <= num_val < 21:
        return "need-level-16-20"
    elif 21 <= num_val < 31:
        return "need-level-21-30"
    elif num_val >= 31:
        return "need-level-31-100"
    return ""

@st.cache_data
def load_region_data(file_path):
    if not os.path.exists(file_path):
        return None
    df = pd.read_excel(file_path)
    df['ID'] = df['ID'].astype(str).str.strip()
    if "Численность населения, чел." in df.columns:
        df["Численность населения, чел."] = df["Численность населения, чел."].astype(float).round(0).astype(int)
    if "Действующие ФП" in df.columns:
        df["Действующие ФП"] = df["Действующие ФП"].astype(float).round(1)
    return df

@st.cache_data
def load_np_data(file_name):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cwd = os.getcwd()
    search_dirs = [cwd, script_dir]
    target_path = None
    for d in search_dirs:
        exact = os.path.join(d, file_name)
        if os.path.exists(exact):
            target_path = exact
            break
    if not target_path:
        for d in search_dirs:
            try:
                for fname in os.listdir(d):
                    if fname.lower() == file_name.lower():
                        target_path = os.path.join(d, fname)
                        break
                if target_path:
                    break
            except Exception:
                pass
    if not target_path:
        import glob
        for d in search_dirs:
            matches = glob.glob(os.path.join(d, "DB_*_NP.xlsx"))
            if matches:
                target_path = matches[0]
                break
    if not target_path:
        return None
    df = pd.read_excel(target_path)
    if "Численность населения, чел." in df.columns:
        df["Численность населения, чел."] = df["Численность населения, чел."].apply(
            lambda x: int(round(float(x))) if pd.notna(x) else 0)
    return df

# =============================================================================
# АГРЕГАТЫ ПО НАСЕЛЕННЫМ ПУНКТАМ "ВНЕ ТЕКУЩЕГО РАЙОНА" ДЛЯ СТРОКИ ОБЛАСТИ
# (districtTable, страница 4, "СЦЕНАРИЙ №4")
# =============================================================================
# Используются в recalcOblastRowAffordabilityAggregates (JS, см. sorting_script
# ниже по файлу) для пересчета показателей строки "Новосибирская область".
# Подробное обоснование выбранного алгоритма — см. комментарий в шапке
# recalcOblastRowAffordabilityAggregates в JS; вкратце: населенные пункты вне
# текущего района не меняются действиями пользователя на этой странице,
# поэтому суммы/счетчики по ним считаются здесь, В PYTHON, ОДИН РАЗ за
# загрузку страницы (с кэшированием через st.cache_data), а не пересчитываются
# в браузере на каждый клик по тысячам строк.

# Названия колонок, из которых считаются агрегаты, — те же самые строки, что
# используются для поиска этих колонок в JS (getAffordabilityCells).
AFFORDABILITY_LEVEL_COL = "Уровень финансовой доступности"
AFFORDABILITY_NEED_CHANGE_COL = "Изменение уровня потребности в развитии дистанционного банковского обслуживания за счет альтернативной инфраструктуры, п.п."

def _parse_percent_like_value(val):
    """Числовой парсинг значения колонки "Уровень ...", ЗЕРКАЛЬНО повторяющий
    логику, которая уже используется при рендере такой же ячейки в npTable
    (см. цикл построения np_rows_html ниже по файлу): убираем '%', заменяем
    ',' на '.', и если получившееся число <= 1.0 — трактуем его как долю и
    домножаем на 100. Любая ошибка/NaN -> 0.0 (совместимо с тем, как
    JS-функция parseNumericCellValue возвращает 0 для пустой/нечисловой
    ячейки — это важно, чтобы Python- и JS-расчеты не расходились)."""
    if pd.isna(val):
        return 0.0
    try:
        num_val = float(str(val).replace('%', '').replace(',', '.').strip())
        if num_val <= 1.0:
            num_val *= 100
        return num_val
    except (ValueError, TypeError):
        return 0.0

def _parse_plain_decimal_value(val):
    """Числовой парсинг значения колонки "Изменение уровня ...": только
    запятая -> точка, без домножения на 100 (в отличие от _parse_percent_like_value
    выше) — точно так же, как при рендере такой же ячейки в npTable/
    districtTable. NaN/ошибка -> 0.0."""
    if pd.isna(val):
        return 0.0
    try:
        return float(str(val).replace(',', '.').strip())
    except (ValueError, TypeError):
        return 0.0

@st.cache_data
def compute_other_districts_affordability_aggregates(np_file_path, region_name):
    """Возвращает суммы/счетчики по колонкам AFFORDABILITY_LEVEL_COL и
    AFFORDABILITY_NEED_CHANGE_COL для ВСЕХ населенных пунктов файла
    np_file_path (DB{date}_NP.xlsx), ЗА ИСКЛЮЧЕНИЕМ населенных пунктов
    текущего района (region_name) — их живые (пересчитанные пользователем)
    значения берутся отдельно из npTable непосредственно в браузере
    (см. computeNpTableAffordabilitySums в JS).

    Результат кэшируется (@st.cache_data) по паре (np_file_path, region_name):
    при повторном открытии той же страницы того же района с теми же данными
    файл не перечитывается и суммы не пересчитываются заново — обычная для
    Streamlit оптимизация "запомнить результат чистой функции по ее
    аргументам", которая идеально подходит для такого рода один раз в сессию
    вычисляемых агрегатов.
    """
    empty_result = {
        "otherLevelSum": 0.0, "otherLevelCount": 0,
        "otherNeedChangeSum": 0.0, "otherNeedChangeCount": 0,
    }

    df = load_np_data(np_file_path)
    if df is None or df.empty or "Район" not in df.columns:
        return empty_result

    other_mask = df["Район"].astype(str).str.strip() != str(region_name).strip()
    other_df = df[other_mask]

    other_level_count = int(len(other_df))
    other_level_sum = 0.0
    other_need_change_sum = 0.0
    other_need_change_count = 0

    if AFFORDABILITY_LEVEL_COL in other_df.columns:
        other_level_sum = float(sum(
            _parse_percent_like_value(v) for v in other_df[AFFORDABILITY_LEVEL_COL]
        ))

    if AFFORDABILITY_NEED_CHANGE_COL in other_df.columns:
        for v in other_df[AFFORDABILITY_NEED_CHANGE_COL]:
            num_val = _parse_plain_decimal_value(v)
            if num_val != 0:
                other_need_change_sum += num_val
                other_need_change_count += 1

    return {
        "otherLevelSum": round(other_level_sum, 4),
        "otherLevelCount": other_level_count,
        "otherNeedChangeSum": round(other_need_change_sum, 4),
        "otherNeedChangeCount": other_need_change_count,
    }

@st.cache_data
def load_indicators(file_path):
    if not os.path.exists(file_path):
        return None
    df = pd.read_excel(file_path, header=None)
    return df

@st.cache_data
def load_nso_summary_data(file_path):
    if not os.path.exists(file_path):
        return None
    df = pd.read_excel(file_path)
    if "Численность населения, чел." in df.columns:
        df["Численность населения, чел."] = df["Численность населения, чел."].astype(float).round(0).astype(int)
    if "Действующие ФП" in df.columns:
        df["Действующие ФП"] = df["Действующие ФП"].astype(float).round(1)
    return df

@st.cache_data
def prepare_svg(svg_path, df_regions, current_date_val, interactive=True, dark_font_regions=None):
    if dark_font_regions is None:
        dark_font_regions = ()
    if not os.path.exists(svg_path):
        return None
    with open(svg_path, "r", encoding="utf-8") as f:
        svg_content = f.read()
    soup = BeautifulSoup(svg_content, "xml")
    svg = soup.find("svg")
    if svg is None:
        return None
    if svg.has_attr("width"):
        del svg["width"]
    if svg.has_attr("height"):
        del svg["height"]
    svg["preserveAspectRatio"] = "xMidYMid meet"

    region_map = {}
    if df_regions is not None and not df_regions.empty:
        for _, row in df_regions.iterrows():
            region_map[str(row["ID"]).strip()] = short_region_name(row["Район"])

    paths = svg.find_all("path")
    for path in paths:
        if not path.has_attr("id"):
            continue
        path_id = path["id"].strip()
        short_name = region_map.get(path_id, path_id)

        if interactive:
            title_tag = soup.new_tag("title")
            title_tag.string = short_name
            path.append(title_tag)

        center_x, center_y = 0, 0
        try:
            d = path.get("d")
            if d:
                svg_path_obj = parse_path(d)
                xmin, xmax, ymin, ymax = svg_path_obj.bbox()
                center_x = (xmin + xmax) / 2
                center_y = (ymin + ymax) / 2
                if short_name == "Куйбышевский":
                    center_y += 18
                    center_x -= 10
                elif short_name == "Доволенский":
                    center_y += 5
                    center_x += 5
                elif short_name == "Карасукский":
                    center_y += 10
                    center_x += 10
        except Exception:
            pass

        label_class = "map-label" if interactive else "heatmap-label"
        text_attrs = {"x": str(center_x), "y": str(center_y), "class": label_class}
        if short_name in dark_font_regions:
            text_attrs["style"] = f"fill: {DARK_FONT_REGION_COLOR};"

        if interactive:
            parent = path.parent
            if parent.name != "a":
                link_tag = soup.new_tag("a", href=f"?region={path_id}&date={current_date_val}", target="_self")
                path.wrap(link_tag)
                if center_x != 0 and center_y != 0:
                    text_tag = soup.new_tag("text", **text_attrs)
                    text_tag.string = short_name
                    link_tag.append(text_tag)
        else:
            if center_x != 0 and center_y != 0:
                text_tag = soup.new_tag("text", **text_attrs)
                text_tag.string = short_name
                svg.append(text_tag)

    return str(svg)

@st.cache_data
def convert_df_to_excel_b64(df, sheet_name='Sheet1'):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
        worksheet = writer.sheets[sheet_name]
        for idx, col in enumerate(df.columns):
            max_len = max(df[col].astype(str).map(len).max(), len(str(col))) + 2
            worksheet.set_column(idx, idx, max_len)
    return base64.b64encode(buffer.getvalue()).decode()

@st.cache_data
def load_file_to_base64(file_path):
    if os.path.exists(file_path):
        with open(file_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

# =============================================================================
# 5. ДИНАМИЧЕСКОЕ ОПРЕДЕЛЕНИЕ ФАЙЛОВ
# =============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SVG_DIR = os.path.join(BASE_DIR, "content", "SVG")
XLS_DIR = os.path.join(BASE_DIR, "content", "xls")

date_suffix = f"_{current_date}"

# SVG_FILE = f"NSO_f{date_suffix}.svg"
# EXCEL_FILE = f"NSO_regions{date_suffix}.xlsx"
# HEATMAP_SVG_FILE = f"NSO_p{date_suffix}.svg"
# EXCEL_F_FILE = f"NSO_f_regions{date_suffix}.xlsx"
# EXCEL_P_FILE = f"NSO_p_regions{date_suffix}.xlsx"
# NP_FILE = f"DB{date_suffix}_NP.xlsx"
# MAIN_INDICATORS_FILE = f"main_indicators{date_suffix}.xlsx"
# NSO_SUMMARY_FILE = f"NSO{date_suffix}.xlsx"

HEATMAP_SVG_FILE = os.path.join(SVG_DIR, f"NSO_f{date_suffix}.svg")
SVG_FILE = os.path.join(SVG_DIR, f"NSO_p{date_suffix}.svg")
EXCEL_FILE = os.path.join(XLS_DIR, f"NSO_regions{date_suffix}.xlsx")
EXCEL_F_FILE = os.path.join(XLS_DIR, f"NSO_f_regions{date_suffix}.xlsx")
EXCEL_P_FILE = os.path.join(XLS_DIR, f"NSO_p_regions{date_suffix}.xlsx")
NP_FILE = os.path.join(XLS_DIR, f"DB{date_suffix}_NP.xlsx")
INDICATORS_FILE = os.path.join(XLS_DIR, f"indicators{date_suffix}.xlsx")
NSO_SUMMARY_FILE = os.path.join(XLS_DIR, f"NSO{date_suffix}.xlsx")

df_regions = load_region_data(EXCEL_FILE)
df_np_all = load_np_data(NP_FILE)
df_indicators = load_indicators(INDICATORS_FILE)

# Мониторим перенос строк
df_indicators = process_excel_linebreaks(df_indicators)
#

df_nso_summary = load_nso_summary_data(NSO_SUMMARY_FILE)

dark_tuple = tuple(DARK_FONT_REGIONS)
interactive_svg = prepare_svg(SVG_FILE, df_regions, current_date, interactive=True, dark_font_regions=dark_tuple)
heatmap_svg = prepare_svg(HEATMAP_SVG_FILE, df_regions, current_date, interactive=False, dark_font_regions=dark_tuple)

if interactive_svg:
    current_page_val = query_params.get("page", "home")
    if isinstance(current_page_val, list):
        current_page_val = current_page_val[0]
    interactive_svg = interactive_svg.replace(
        'href="?region=', 
        f'href="?from_page={current_page_val}&region='
    )

b64_manual = load_file_to_base64("Руководство пользователя.zip")
b64_tfd = load_file_to_base64("Как открыть ТФД.zip")
b64_fp = load_file_to_base64("Как назначить ФП.zip")
b64_tcash = load_file_to_base64("Как подключить точку кэшаут.zip")

b64_sfo_map = load_file_to_base64("Интерактивная карта СФО.xlsm")
b64_excel_f = load_file_to_base64(EXCEL_F_FILE)
b64_excel_p = load_file_to_base64(EXCEL_P_FILE)

display_df = df_regions.copy() if df_regions is not None else pd.DataFrame()

# =============================================================================
# 6. НАВИГАЦИЯ
# =============================================================================
def go_home():
    st.session_state.page = 'home'
    st.session_state.selected_region = None
    if "region" in query_params:
        del query_params["region"]
    if "page" in query_params:
        del query_params["page"]
    if "show_contacts" in query_params:
        del query_params["show_contacts"]

if has_region_param:
    requested_region_id = str(query_params["region"]).strip()
    if df_regions is not None and not df_regions.empty and requested_region_id in df_regions['ID'].astype(str).str.strip().values:
        st.session_state.selected_region = query_params["region"]
        st.session_state.page = 'district'
    else:
        go_home()
        st.rerun()
else:
    page_param = query_params.get("page", "")
    if isinstance(page_param, list):
        page_param = page_param[0]
    if page_param == "page2":
        st.session_state.page = 'page2'
    elif page_param == "page3":
        st.session_state.page = 'page3'
    elif st.session_state.get('page') == 'district' and not has_region_param:
        go_home()
    elif 'page' not in st.session_state:
        st.session_state.page = 'home'
        st.session_state.selected_region = None

# =============================================================================
# 7. CSS СТИЛИЗАЦИЯ
# =============================================================================
st.markdown(f"""
<style>
{font_faces_css}

:root {{
    --font-ui: 'Golos UI', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    --font-text: 'Golos Text', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
}}

body, .stApp, .stMarkdown, .stText, p, span, div {{
    font-family: var(--font-text);
    font-variant-numeric: lining-nums tabular-nums;
}}

div[data-testid="stMarkdownContainer"] {{
    min-height: 20px !important;
    padding-top: 0rem !important;
    padding-bottom: 0rem !important;
}}

.block-container {{
    padding-top: 0rem !important;
    padding-bottom: 5rem;
    max-width: 100%;
}}

.stAppHeader {{ display: none; }}

.header-container {{
    background: #ffffff;
    border-radius: 16px;
    padding: 24px 20px 10px 20px;
    margin-top: -5px !important;
    margin-bottom: 20px;
    text-align: center;
}}

.main-title h1 {{
    font-family: var(--font-ui);
    font-size: 38px !important;
    font-weight: 700 !important;
    color: #1a252c !important;
    margin: 0 0 15px 0 !important;
    padding: 0 !important;
    line-height: 1.3 !important;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    letter-spacing: -0.02em;
}}

.main-title h1 span.icon {{
    font-size: 28px;
    filter: drop-shadow(0 2px 4px rgba(0,0,0,0.1));
}}

/* Полное скрытие элементов управления заголовками Streamlit */
[data-testid="stHeaderActionElements"],
h1 a.anchor-link, h2 a.anchor-link, h3 a.anchor-link {{
    display: none !important;
}}

/* Убираем отступы и выравниваем заголовки строго по центру */
.main-title h1 {{
    display: block !important; /* Убираем flex, который сдвигался из-за скрытой иконки */
    text-align: center !important;
}}

.sub-title {{
    text-align: center !important;
}}
.sub-title h4 {{
    font-family: var(--font-ui);
    font-size: 18px !important;
    font-weight: 600 !important;
    color: #1a252c !important;
    margin: 0 0 5px 0 !important;
    padding: 0 !important;
    text-align: center !important;
}}
.sub-title p {{
    font-size: 14px !important;
    color: #626d7a !important;
    margin: 0 !important;
    text-align: center !important;
}}

.date-picker-wrapper [data-baseweb="select"] {{
    background-color: #f8f9fa !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 8px !important;
    font-family: var(--font-ui) !important;
    font-size: 15px !important;
    font-weight: 500 !important;
    color: #1a252c !important;
    height: 40px !important;
    padding-top: 8px !important;
    padding-left: 10px !important;
    box-shadow: none !important;
    margin: 0 auto !important;
    cursor: pointer !important;
    caret-color: transparent !important;
    user-select: none !important;
}}
.date-picker-wrapper [data-baseweb="select"]:hover {{
    border-color: #2980b9 !important;
}}
.date-picker-wrapper [data-baseweb="select"] svg {{
    fill: #1a252c !important;
}}
.date-picker-wrapper [data-baseweb="select"] input {{
    cursor: pointer !important;
    caret-color: transparent !important;
    -webkit-user-select: none;
    -moz-user-select: none;
    -ms-user-select: none;
    pointer-events: none !important;
    user-select: none !important;
}}

/* ===== НАВИГАЦИОННЫЕ КАРТОЧКИ ГЛАВНОЙ СТРАНИЦЫ ===== */
.nav-cards-row {{
    display: flex;
    justify-content: center;
    gap: 60px;
    margin: 25px auto 25px auto;
    max-width: 1100px;
}}
.nav-card {{
    flex: 1;
    max-width: 530px;
    min-height: 110px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background-color: #ffffff;
    border: 1px solid rgba(49, 51, 63, 0.2);
    border-radius: 14px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    padding: 22px 28px;
    text-decoration: none !important;
    cursor: pointer;
    transition: border-color 0.2s, transform 0.15s, box-shadow 0.2s;
}}
.nav-card:hover {{
    border-color: #2980b9 !important;
    transform: translateY(-3px);
    box-shadow: 0 6px 16px rgba(41,128,185,0.12);
}}
.nav-card:active {{
    transform: translateY(1px);
    box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}}
.nav-card-line1 {{
    font-family: var(--font-ui);
    font-size: 17px;
    font-weight: 600;
    color: #1a252c;
    text-align: center;
    line-height: 1.35;
    margin-bottom: 6px;
}}
.nav-card:hover .nav-card-line1 {{
    color: #2980b9;
}}
.nav-card-line2 {{
    font-family: var(--font-text);
    font-size: 13px;
    font-weight: 400;
    color: #626d7a;
    text-align: center;
    line-height: 1.3;
}}

/* ===== КНОПКИ ГЛАВНОЙ СТРАНИЦЫ (НИЖНИЙ РЯД) ===== */
.home-btns-row {{
    display: flex;
    justify-content: center;
    gap: 420px;
    margin: 12px auto 0px auto;
    max-width: 1100px;
}}

.home-btn {{
    flex: 1;
    max-width: 330px;
    height: 90px;
    display: flex;
    align-items: center;
    justify-content: center;
    background-color: rgb(255, 255, 255);
    border: 1px solid rgba(49, 51, 63, 0.2);
    border-radius: 12px;
    box-shadow: rgba(0, 0, 0, 0.05) 0px 1px 2px 0px;
    font-family: var(--font-ui);
    font-size: 16px;
    font-weight: 550;
    line-height: 1.25;
    color: rgb(49, 51, 63);
    text-align: center;
    text-decoration: none;
    cursor: pointer;
    transition: border-color 0.2s, color 0.2s, transform 0.1s, box-shadow 0.2s;
    box-sizing: border-box;
}}

a.home-btn {{
    font-family: var(--font-ui);
    font-size: 17px;
    font-weight: 600;
    color: #1a252c;
    text-align: center;
    line-height: 1.35;
    text-decoration: none;
}}

.home-btn:hover {{
    border-color: #2980b9;
    color: #2980b9;
    transform: translateY(-3px);
    box-shadow: 0 6px 16px rgba(41,128,185,0.12);

}}
.home-btn:active {{
    transform: translateY(1px);
    box-shadow: 0 1px 2px 0 rgba(0,0,0,0.05);
    background-color: #f8fafc;
}}
.home-btn-disabled {{
    opacity: 0.5;
    cursor: default;
    pointer-events: none;
}}

/* ===== КНОПКИ ПОРТАЛА (ОБЩИЕ) ===== */
.portal-btn, div.stButton > button {{
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 300px !important;
    height: 90px !important;
    background-color: rgb(255, 255, 255) !important;
    border: 1px solid rgba(49, 51, 63, 0.2) !important;
    border-radius: 12px !important;
    box-shadow: rgba(0, 0, 0, 0.05) 0px 1px 2px 0px !important;
    margin: 0 !important; padding: 0 !important;
    box-sizing: border-box !important;
    transition: border-color 0.2s, color 0.2s, background-color 0.2s, transform 0.1s !important;
    user-select: none !important; cursor: pointer !important;
    text-decoration: none !important;
}}
.portal-btn,
div.stButton > button,
div.stButton > button p,
div.stButton > button span {{
    font-family: var(--font-ui) !important;
    font-size: 16px !important;
    font-weight: 550 !important;
    font-style: normal !important;
    line-height: 1.2 !important;
    color: rgb(49, 51, 63) !important;
    text-decoration: none !important;
}}
div.stButton > button p {{
    margin: 0 !important;
    padding: 0 !important;
}}
.portal-btn:hover, div.stButton > button:hover,
div.stButton > button:hover p, div.stButton > button:hover span {{
    border-color: rgb(41,128,185) !important; color: rgb(41,128,185) !important;
    background-color: rgb(255, 255, 255) !important;
}}
.portal-btn:active, div.stButton > button:active,
div.stButton > button:active p, div.stButton > button:active span {{
    color: rgb(41,128,185) !important; border-color: rgb(41,128,185) !important;
}}
.portal-btn:hover, div.stButton > button:hover {{
    border-color: #2980b9 !important;
    color: #2980b9 !important;
    transform: translateY(-2px) !important;
    box-shadow: 0 4px 6px -1px rgba(41, 128, 185, 0.1), 0 2px 4px -1px rgba(41, 128, 185, 0.06) !important;
}}
.portal-btn:active, div.stButton > button:active {{
    transform: translateY(1px) !important;
    box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05) !important;
    background-color: #f8fafc !important;
}}
div.stButton {{
    display: flex;
    justify-content: flex-start;
    margin: 0 !important;
    padding: 0 !important;
}}
div.stButton, [data-testid="stColumn"], [data-testid="stVerticalBlock"] {{
    gap: 0 !important;
}}

/* ===== КНОПКИ В ЛЕВОЙ ПАНЕЛИ (СТРАНИЦЫ 2 И 3) ===== */
.left-panel-btn {{
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
    justify-content: center !important;
    width: 100% !important; min-width: 100% !important; max-width: 100% !important;
    height: auto !important; min-height: 70px !important;
    background-color: #ffffff !important;
    border: 1px solid rgba(49, 51, 63, 0.2) !important;
    border-radius: 10px !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;
    padding: 12px 14px !important;
    margin: 40px 0 20px 0 !important;
    box-sizing: border-box !important;
    transition: border-color 0.2s, transform 0.15s, box-shadow 0.2s !important;
    cursor: pointer !important;
    text-decoration: none !important;
}}
.left-panel-btn:hover {{
    border-color: #2980b9 !important;
    transform: translateY(-2px) !important;
    box-shadow: 0 4px 10px rgba(41,128,185,0.1) !important;
}}
.left-panel-btn:active {{
    transform: translateY(1px) !important;
}}
.left-panel-btn-line1 {{
    font-family: var(--font-ui) !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    color: #1a252c !important;
    text-align: center !important;
    line-height: 1.3 !important;
    text-decoration: none !important;
}}
.left-panel-btn:hover .left-panel-btn-line1 {{
    color: #2980b9 !important;
}}
.left-panel-btn-line2 {{
    font-family: var(--font-text) !important;
    font-size: 12px !important;
    font-weight: 400 !important;
    color: #626d7a !important;
    text-align: center !important;
    line-height: 1.3 !important;
    margin-top: 4px !important;
    text-decoration: none !important;
}}

/* ===== КНОПКА «ВОЗВРАТ НА ГЛАВНУЮ СТРАНИЦУ» ===== */
.back-btn-container {{
    margin-top: 30px !important; 
    margin-bottom: 15px !important; 
    display: block !important;
}}
.back-btn-container div.stButton > button {{
    width: auto !important; min-width: 180px !important; max-width: auto !important;
    height: 40px !important; min-height: 40px !important; max-height: 40px !important;
    border-radius: 8px !important; padding: 0 16px !important;
    font-size: 14px !important; font-weight: 550 !important;
}}
.back-btn-container div.stButton {{
    justify-content: flex-start;
}}
.back-btn-container div.stButton > button p,
.back-btn-container div.stButton > button span {{
    font-size: 14px !important;
}}
.back-btn-container div.stButton > button:hover {{ border-color: rgb(41,128,185) !important; color: rgb(41,128,185) !important; }}
.back-btn-container div.stButton > button:hover p,
.back-btn-container div.stButton > button:hover span {{ color: rgb(41,128,185) !important; }}
.back-btn-container div.stButton > button:active {{ border-color: rgb(41,128,185) !important; color: rgb(41,128,185) !important; background-color: #f8fafc !important; transform: translateY(1px) !important; }}
.back-btn-container div.stButton > button:active p,
.back-btn-container div.stButton > button:active span {{ color: rgb(41,128,185) !important; }}

/* ===== ССЫЛКА «ВОЗВРАТ НА ПРЕДЫДУЩУЮ СТРАНИЦУ» ===== */
.back-link {{
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    height: 90px !important;
    padding: 0 16px !important;
    border-radius: 8px !important;
    font-size: 16px !important;
    font-weight: 550 !important;
    font-family: var(--font-ui) !important;
    color: rgb(49, 51, 63) !important;
    text-decoration: none !important;
    border: 1px solid rgba(49, 51, 63, 0.2) !important;
    background: #fff !important;
    cursor: pointer !important;
    transition: border-color 0.2s, color 0.2s, transform 0.1s, box-shadow 0.2s !important;
}}

.back-link:hover {{
    border-color: #2980b9 !important;
    color: #2980b9 !important;
    transform: translateY(-3px);
    box-shadow: 0 6px 16px rgba(41,128,185,0.12);
}}
.back-link:active {{
    transform: translateY(1px);
    box-shadow: 0 1px 2px 0 rgba(0,0,0,0.05);
    background-color: #f8fafc;
}}

/* ===== ИНДИКАТОРНЫЕ КАРТОЧКИ ===== */
.indicators-row {{
    display: flex;
    gap: 40px;
    margin-bottom: 20px;
    margin-top: 30px;    
    flex-wrap: nowrap;
}}
.indicator-card {{
    flex: 1;
    background: #f8f9fa;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 12px 8px;
    text-align: center;
    display: flex;
    flex-direction: column;
    justify-content: center;
    min-height: 75px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    position: relative; /* Добавлено для привязки тултипа */
}}
.indicator-card-tall {{
    min-height: 98px !important;
}}

.card-line1 {{
    font-family: var(--font-ui);
    font-size: 17px;
    font-weight: 600;
    color: #2980b9;
    line-height: 1.3;
}}
.card-line2 {{
    font-family: var(--font-text);
    font-size: 18px;
    font-weight: 600;
    color: #64748b;
    margin-top: 4px;
    margin-bottom: 4px;
    line-height: 1.3;
}}
.card-line3 {{
    font-family: var(--font-text);
    font-size: 14px;
    color: #64748b;
    line-height: 1.3;
}}

div.indicator-card.indicator-card-tall {{
  /* Подключение анимации появления */
  animation: smoothAppear 0.4s ease-out forwards;

border: #1E40AF 3px solid;
border: #0D5C3A 3px solid;
border: #00875A 3px solid;
border: #02bd34 3px solid;
box-shadow: 0 14px 12px rgba(0, 0, 0, 0.18)
}}

/* Описание анимации от 90% размера к 110% */
@keyframes smoothAppear {{
  from {{
    opacity: 0;
    transform: scale(0.90); /* Начинает с чуть меньшего размера */
  }}
  to {{
    opacity: 1;
    transform: scaleY(1.1); /* Возвращается к исходному размеру */
  }}
}}

/* Стиль для круглой иконки «i» справа сверху */
.info-icon {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    border: 1px solid #cbd5e1;
    border-radius: 50%;
    color: #64748b;
    font-size: 16px;
    font-weight: bold;
    background-color: #ffffff;
    transition: all 0.2s;
}}

.info-icon:hover {{
    background-color: #f1f5f9;
    color: #1e293b;
    border-color: #475569;
}}

/* Относительное позиционирование для иконки, чтобы подсказка привязывалась к ней */
.info-icon-wrapper {{
    position: absolute;
    top: -15px;
    right: -20px;
    cursor: help;
}}

/* Стили для иконки тултипа при наведении*/
.info-icon-wrapper:hover .info-icon {{
    background-color: #f1f5f9;
    color: #1e293b;
    border-color: #475569;
    border: 1px solid #02bd34;
    font-style: italic;
}}

/* Стили для кастомного прямоугольного тултипа */
.custom-tooltip {{
    visibility: hidden;
    opacity: 0;
    position: absolute;
    top: -34px;
    right: 16px;
    width: 350px; /* Фиксированная ширина блока */
    padding: 8px 12px;
    background-color: #ffffff;
    color: #1e293b;
    font-size: 14px;
    line-height: 1.4;
    border-radius: 8px;        /* Тот самый скругленный прямоугольник */
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1); /* Воздушная современная тень */    
    z-index: 10;
    transition: opacity 0.5s ease, visibility 0.5s ease;
    text-align: left;
    border: 2px solid #f1f5f9; /* Тонкая рамка для четкости границ */
    z-index: 100;
    pointer-events: none; /* Чтобы тултип не перехватывал события мыши */
}}

/* Плавное появление при наведении на обертку иконки */
.info-icon-wrapper:hover .custom-tooltip {{
    visibility: visible;
    opacity: 1;
}}

/* ===== SVG КАРТЫ ===== */
@keyframes mapEntrance {{
    from {{ opacity: 0; transform: scale(0.95) translateY(10px); }}
    to {{ opacity: 1; transform: scale(1) translateY(0); }}
}}
.svg-wrapper {{ width: 100%; display: flex; justify-content: center; align-items: center; margin-top: 10px; margin-bottom: 15px; overflow: visible; }}
.svg-wrapper svg {{ width: 100%; max-width: 100%; height: auto !important; max-height: none; display: block; overflow: visible !important; }}
.svg-wrapper a {{ text-decoration: none; display: block; outline: none; transform-origin: center !important; transition: transform 0.25s ease, filter 0.25s ease !important; }}
.svg-wrapper path {{ fill: #e0e0e0; stroke: #ffffff; stroke-width: 1; transition: fill 0.25s ease, stroke 0.25s ease !important; cursor: pointer; }}
.map-label {{ font-family: var(--font-ui); font-size: 9px; font-weight: 600; fill: #111111; text-anchor: middle; pointer-events: none; user-select: none; paint-order: stroke; stroke: white; stroke-width: 1.5px; stroke-linejoin: round; }}
.svg-wrapper a:hover {{ transform: scale(1.015) translateY(-2px) !important; filter: drop-shadow(0px 6px 10px rgba(0, 0, 0, 0.3)) !important; position: relative; z-index: 9999 !important; }}
.svg-wrapper a:hover path {{ fill: #3498db !important; stroke: #1f5f8b !important; }}

/* Тепловая карта (без интерактивности) */
.heatmap-wrapper {{ width: 90%; display: flex; justify-content: center; align-items: center; margin-top: 10px; margin-bottom: 15px; overflow: visible; }}
.heatmap-wrapper svg {{ width: 60%; max-width: 60%; height: auto !important; max-height: none; display: block; overflow: visible !important; }}
.heatmap-wrapper path {{ stroke: #ffffff; stroke-width: 0.5; pointer-events: none; }}
.heatmap-label {{ font-family: var(--font-ui); font-size: 9px; font-weight: 600; fill: #111111; text-anchor: middle; pointer-events: none; user-select: none; paint-order: stroke; stroke: white; stroke-width: 2px; stroke-linejoin: round; }}

/* Карта на 50% ширины (страница 3) */
.svg-wrapper-50 {{ width: 50%; margin: 0 auto; }}
.svg-wrapper-50 .svg-wrapper {{ width: 100%; }}

/* ===== ТЕКСТОВЫЕ БЛОКИ ГЛАВНОЙ ===== */
.home-info-text {{
    font-family: var(--font-text);
    font-size: 18px;
    color: #333;
    line-height: 1.8;
    max-width: 1100px;
    margin: 15px auto;
}}

/* Применяем отступ и выравнивание ко всем абзацам внутри блока */
.home-info-text p {{
    text-indent: 1.25cm;
    text-align: justify;
    margin: 0 0 0 0; /* отступ снизу между абзацами */
}}

/* ===== ЛЕГЕНДА ТЕПЛОВОЙ КАРТЫ ===== */
.heatmap-legend {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    margin-top: 15px;
    margin-bottom: 50px;
    flex-wrap: wrap;
}}
.heatmap-legend-line {{
    width: 45px;
    height: 3px;
    background-color: #e74c3c;
    flex-shrink: 0;
    border-radius: 2px;
}}
.heatmap-legend-text {{
    font-family: var(--font-text);
    font-size: 13px;
    color: #333;
    line-height: 1.3;
}}

/* ===== ТАБЛИЦЫ ===== */
table {{ width: 100% !important; border-collapse: collapse !important; font-size: 14px !important; margin-top: 15px !important; }}
table thead tr th {{
    font-family: var(--font-text); font-weight: 600 !important; font-size: 14px !important;
    background-color: #f8f9fa !important; color: #000000 !important; text-align: center !important;
    border: 1px solid #dcdcdc !important; padding: 10px !important; vertical-align: middle !important;
    position: sticky !important; top: 0 !important; z-index: 100 !important;
    font-variant-numeric: lining-nums tabular-nums;
}}
table tbody tr td {{
    font-family: var(--font-text); font-weight: 400 !important; font-size: 14px !important;
    text-align: center !important; color: #222222 !important; border: 1px solid #dcdcdc !important;
    padding: 6px !important; vertical-align: middle !important;
    font-variant-numeric: lining-nums tabular-nums;
}}
table tbody tr td:first-child {{ text-align: left !important; padding-left: 15px !important; }}
table a {{ color: #0066cc !important; text-decoration: none !important; font-weight: 500 !important; transition: color 0.15s ease; }}
table a:hover {{ color: #004499 !important; text-decoration: underline !important; }}
table tbody tr {{ transition: background-color 0.6s ease; }}
table tbody tr:hover {{ background-color: #f1f7fc !important; cursor: pointer; }}

.need-level-0-10 {{ background-color: #88A945 !important; }}
.need-level-11-15 {{ background-color: #D8E4BC !important; }}
.need-level-16-20 {{ background-color: #FFFFCC !important; }}
.need-level-21-30 {{ background-color: #FCD5B4 !important; }}
.need-level-31-100 {{ background-color: #E6B8B7 !important; }}

@keyframes rowPulse {{ 0% {{ background-color: rgba(52, 152, 219, 0.25); }} 100% {{ background-color: transparent; }} }}
.pulse-highlight {{ animation: rowPulse 0.6s ease-out forwards; }}
.sort-arrow {{ display: inline-block; margin-left: 8px; font-size: 15px; vertical-align: middle; }}

/* ===== ТАБЛИЦЫ УРОВНЕЙ (ЛЕВАЯ ПАНЕЛЬ) ===== */
.weights-table, .Needs-table {{
    font-size: 16px !important;
}}
.weights-table {{
    margin-top: 80px !important;
}}
.Needs-table {{
    margin-top: 140px !important;
    margin-bottom: 67px !important;
}}
.weights-table thead tr th, .Needs-table thead tr th {{
    background-color: #f1f5f9 !important;
    padding: 8px 6px !important;
    font-size: 14px !important;
}}
.weights-table tbody tr td, .Needs-table tbody tr td {{
    padding: 7px 6px !important;
    font-size: 14px !important;
}}
.weights-table tbody tr td:first-child, .Needs-table tbody tr td:first-child {{
    text-align: center !important;
    padding-left: 6px !important;
}}




/* ===== РАЗДЕЛИТЕЛИ ===== */
.custom-separator {{
    height: 1px;
    width: 100%;
    background: linear-gradient(to right, rgba(0,0,0,0) 0%, rgba(0,0,0,0.8) 50%, rgba(0,0,0,0) 100%);
    margin: 20px auto;
}}
.custom-separator800 {{ max-width: 800px; }}

.custom-separator1000 {{ max-width: 1000px; }}

/* ===== СТРАНИЦА РАЙОНА ===== */
.district-section-title {{
    font-family: var(--font-ui); 
    font-size: 17px; 
    font-weight: 600;
    color: #1a252c; 
    margin-top: 20px; 
    margin-bottom: 12px;
    text-align: center;
}}
.sort-caption {{
    font-family: var(--font-text); font-size: 13px; color: #666;
    margin-top: 5px; margin-bottom: 15px; font-weight: 400;
    text-align: center;
}}
.contacts-info-card {{
    background-color: #f8f9fa; border-left: 5px solid rgb(41,128,185);
    padding: 20px; border-radius: 8px; margin-top: 20px;
    max-width: 500px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    font-size: 14px;
}}

/* ===== ТАБЛИЦА НАСЕЛЕННЫХ ПУНКТОВ ===== */

/* делаем колонки "Район" и "Населенный пункт" шириной 165px, чтобы названия НП входили без переноса*/
#districtTable > thead > tr > th:nth-child(1), 
#npTable > thead > tr > th:nth-child(1) {{
    width: 165px !important;
}}

/* ===== ФИКСАЦИЯ ТАБЛИЦЫ districtTable ПРИ СКРОЛЛЕ (страница 4) ===== */
/* Общее правило "table thead tr th {{ position: sticky; ... }}" выше по файлу
   прилипает только к строке заголовка и конфликтует с идеей "прилипает вся
   таблица целиком" (заголовок и обе строки данных остаются видны одновременно,
   а не наслаиваются друг на друга). Поэтому для districtTable отключаем
   стандартный sticky у заголовка. */
#districtTable thead tr th {{
    position: static !important;
    top: auto !important;
}}
/* ПОПЫТКА №2 (через position: sticky на едином враппере вокруг таблицы)
   тоже не сработала: где-то в цепочке предков этого враппера Streamlit
   обрезает/ограничивает sticky-контекст (типично для верстки на flex-блоках
   с overflow, которые генерирует сам Streamlit под капотом, и предсказать
   заранее без инспекции в браузере, какой именно предок виноват, нельзя).
   Поэтому вместо CSS sticky вся фиксация теперь полностью реализована на
   JS через position: fixed — см. функцию syncDistrictTableSticky в блоке
   "8. JS СКРИПТ ДЛЯ СОРТИРОВКИ ТАБЛИЦ" ниже. Она не зависит от того, какой
   именно элемент физически скроллится, и работает даже под предками с
   overflow: hidden/scroll и css transform. */
#districtTablePlaceholder {{
    width: 100%;
}}

/* ===== ПЕРЕКЛЮЧАТЕЛЬ "ДА/НЕТ" СО СТРЕЛОЧКАМИ (npTable) ===== */
#npTable td.np-toggle-cell {{
    padding: 4px 6px !important;
    text-align: center !important;
}}
.toggle-widget {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
}}
.toggle-value {{
    min-width: 30px;
    display: inline-block;
    font-weight: 600;
    font-family: var(--font-ui);
}}
.toggle-arrow {{
    -webkit-user-select: none;
    -moz-user-select: none;
    -ms-user-select: none;
    user-select: none;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    padding: 0;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    background-color: #ffffff;
    font-size: 11px;
    line-height: 1;
    transition: background-color 0.15s, border-color 0.15s;
}}
.toggle-arrow-up {{
    color: #27ae60;
}}
.toggle-arrow-down {{
    color: #e74c3c;
}}
.toggle-arrow-up:hover {{
    background-color: #e8f8f5;
    border-color: #27ae60;
}}
.toggle-arrow-down:hover {{
    background-color: #fdedec;
    border-color: #e74c3c;
}}
#npTable td.np-toggle-cell[data-state="yes"] .toggle-value {{
    color: #27ae60;
}}
#npTable td.np-toggle-cell[data-state="no"] .toggle-value {{
    color: #e74c3c;
}}

/* Стиль div для кнопок страницы 4*/
.centered-portal-btn{{
    display: flex; 
    justify-content: center; 
    margin-top: 25px;
    width: 100%; /* Гарантирует, что контейнер занимает всю ширину колонки */
}}

/* ширина кнопок внизу страницы 4 (НП)*/
.w400{{
    width: 400px !important;
}}

.weights-correct {{
    margin-top: 0 !important;
}}
#weights_np tr th, #npTable tr th {{
    position: static !important;
}}

/* Повышаем приоритет цвета для стрелок СТРАНИЦЫ 4 селектором таблицы */
table tbody tr td.change-pos-custom {{ 
    color: #27ae60 !important; 
    font-weight: bold !important; 
}}
table tbody tr td.change-neg-custom {{
    color: #e74c3c !important; 
    font-weight: bold !important; 
}}

/* ===== ВИЗУАЛЬНАЯ "ВСПЫШКА" ПРИ ПРОГНОЗНОМ ПЕРЕСЧЕТЕ ЗНАЧЕНИЙ (npTable, districtTable) ===== */
/* По просьбе заказчика: просто смена цифр (даже жирным шрифтом/другим цветом)
   в ячейке — незаметна. Добавляем короткую анимацию "круги по воде": ячейка
   на мгновение подсвечивается и от нее расходится затухающая красная обводка
   (через box-shadow с растущим радиусом и убывающей прозрачностью). Класс
   .value-flash навешивается через JS (см. flashCell в JS-блоке ниже) на
   каждую ячейку, значение которой было только что пересчитано.

   ВАЖНЫЙ НЮАНС про ячейки "Уровень потребности..." в строках области/района,
   которые дополнительно заливаются цветом через классы .need-level-* с
   background-color: ... !important (см. applyNeedLevelFill в setLevelCellValue):
   анимация здесь висит ПРЯМО на фоне td (как и просили), поэтому пробовать
   перебить !important самой анимацией бессмысленно — !important внутри
   @keyframes браузеры по спецификации CSS игнорируют, а обычная (без
   !important) анимация background-color в любом случае имеет более низкий
   приоритет в каскаде, чем !important-правило .need-level-*.
   Более ранняя попытка обойти это через отдельный слой (::after с
   абсолютным позиционированием и растущим box-shadow) визуально ломалась:
   box-shadow на псевдоэлементе выходил за границы td и накладывался на
   соседние ячейки, из-за чего вспышки выглядели как отдельные разъезжающиеся
   прямоугольники разного размера.
   Вместо слоев — ОЧЕРЕДНОСТЬ (реализована в JS, в setLevelCellValue): для
   ячеек с заливкой класс .need-level-* применяется НЕ сразу, а только ПОСЛЕ
   того как отыграет вспышка (className на время анимации становится пустым,
   поэтому background-color в @keyframes ничем не перебивается и вспышка
   полностью видна), и только по ее завершении применяется цвет заливки —
   визуально ровно "сначала мигнули красным, потом залилось цветом".
*/
@keyframes cellValueFlash {{
    0%   {{ box-shadow: 0 0 0 0 rgba(255, 0, 0, 0.85); background-color: rgba(255, 0, 0, 0.45); }}
    60%  {{ box-shadow: 0 0 0 16px rgba(255, 0, 0, 0); background-color: rgba(255, 0, 0, 0.10); }}
    100% {{ box-shadow: 0 0 0 16px rgba(255, 0, 0, 0); background-color: transparent; }}
}}
td.value-flash {{
    animation: cellValueFlash 1.0s ease-out;
    position: relative;
    z-index: 1;
}}


/* ===== ЗАГОЛОВОК ПРАВОЙ ЧАСТИ (СТРАНИЦЫ 2 И 3) ===== */
.right-panel-title {{
    font-family: var(--font-ui);
    font-size: 20px;
    font-weight: 600;
    color: #1a252c;
    text-align: center;
    margin: 40px 0 15px 0;
    line-height: 1.35;
}}

/* ===== ФУТЕР ===== */
.footer {{
    width: calc(100% + 10rem) !important; margin-left: -5rem !important; margin-right: -5rem !important;
    position: relative;
    background-color: #1e293b;
    text-align: center;
    padding: 30px 20px 35px 20px; font-size: 15px;
    color: #cbd5e1;
    border-top: 1px solid #334155; margin-top: 60px; margin-bottom: -5rem !important;
    font-family: var(--font-text); font-variant-numeric: lining-nums tabular-nums;
}}
.footer strong {{
    color: #38bdf8 !important;
    background: rgba(56, 189, 248, 0.15);
    border: 1px solid rgba(56, 189, 248, 0.4);
    padding: 3px 10px;
    margin-left: 5px; border-radius: 6px; font-weight: 600; display: inline-block;
    font-family: var(--font-ui);
}}

th {{
    -webkit-user-select: none;
    -moz-user-select: none;
    -ms-user-select: none;
    user-select: none;
    cursor: pointer;
}}

.content-spacer {{ display: none !important; }}

.left-panel-section {{
    padding-right: 5px;
}}

/* ===== КОНТЕЙНЕР ТАБЛИЦЫ КОНТАКТОВ ===== */
.contacts-table-container {{
    max-width: 900px; 
    margin: 25px auto 0 auto; 
    background: #ffffff;
    border: 1px solid #e2e8f0; 
    border-radius: 14px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.08);
    overflow: hidden;
    animation: contactsFadeIn 0.3s ease;
    scroll-margin-bottom: 50px;
}}
@keyframes contactsFadeIn {{ from {{ opacity: 0; transform: translateY(-10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
.contacts-table-header {{
    display: flex; 
    align-items: center; 
    justify-content: space-between;
    padding: 16px 24px; 
    border-bottom: 1px solid #e2e8f0;
    font-family: var(--font-ui); 
    font-size: 16px; 
    font-weight: 600; 
    color: #1a252c;
}}
.contacts-table-close {{
    font-size: 20px; color: #626d7a; text-decoration: none !important;
    cursor: pointer; padding: 2px 8px; border-radius: 6px;
    transition: background-color 0.15s, color 0.15s; line-height: 1;
}}
.contacts-table-close:hover {{ background-color: #f1f5f9; color: #1a252c; }}
.contacts-table-container table {{ margin: 0 !important; }}
.contacts-table-container table thead tr th {{ background-color: #f8f9fa !important; }}
.contacts-table-container table tbody tr td:first-child {{
    text-align: center !important; padding-left: 6px !important;
}}
.contacts-header{{
margin: 0 auto;
}}
div.stButton > button.portal-streamlit-btn:hover {{
    border-color: #2980b9 !important; 
    color: #2980b9 !important;
    transform: translateY(-2px) !important;
    box-shadow: 0 4px 6px -1px rgba(41,128,185,0.1), 0 2px 4px -1px rgba(41,128,185,0.06) !important;
}}
div.stButton > button.portal-streamlit-btn:hover p,
div.stButton > button.portal-streamlit-btn:hover span {{
    color: #2980b9 !important;
}}
</style>
""", unsafe_allow_html=True)

# =============================================================================
# 8. JS СКРИПТ ДЛЯ СОРТИРОВКИ ТАБЛИЦ
# =============================================================================
sorting_script = """
<script>
const parentDoc = window.parent.document;
try {
    if (parentDoc) {
        parentDoc.documentElement.lang = 'ru';
        const mainAppContainer = parentDoc.querySelector('.block-container') || parentDoc.querySelector('section.main');
        if (mainAppContainer && !mainAppContainer.hasAttribute('role')) {
            mainAppContainer.setAttribute('role', 'main');
        }
    }
} catch (e) {}

function lockSelectInput() {
    const inputs = parentDoc.querySelectorAll('.date-picker-wrapper input');
    inputs.forEach(input => {
        if (!input.readOnly) {
            input.readOnly = true;
        }
        input.style.caretColor = 'transparent';
        input.style.cursor = 'pointer';
    });
}

// Колонки, которые на странице района отображаются как переключатель "да/нет"
const TOGGLE_YES_NO_COLUMNS = [
    'Количество точек финансового доступа',
    'Количество Финансовых помощников',
    'Количество торговых точек с сервисом "Выдача наличных на кассе"'
];

// Находит индекс колонки в таблице по атрибуту data-colname у <th>
function getColumnIndexByName(table, colName) {
    if (!table || !table.tHead || !table.tHead.rows[0]) return -1;
    const headers = Array.from(table.tHead.rows[0].cells);
    return headers.findIndex(h => h.dataset && h.dataset.colname === colName);
}

// Пересчитывает суммарное количество "да" по каждому переключателю
// в npTable и обновляет соответствующие ячейки строки района в districtTable.
// Дополнительно: если пересчитанное значение действительно изменилось,
// ячейка districtTable подсвечивается той же "вспышкой" (flashCell), что и
// пересчитанные ячейки строки населенного пункта в npTable — чтобы изменение
// было заметно одновременно в обеих таблицах. Функция flashCell объявлена
// ниже по файлу (в блоке "ПРОГНОЗНЫЙ ПЕРЕСЧЕТ..."), но т.к. это объявление
// function (а не const/let), оно поднимается (hoisting) и доступно здесь.
//
// Параметр triggeredByUserClick (по умолчанию false) — ИСПРАВЛЕНИЕ ГЛЮКА:
// эта функция вызывается из ДВУХ мест — (1) сразу после клика пользователя
// по стрелочке "да/нет" и (2) каждые 500мс из общего setInterval как
// подстраховка на случай, если Streamlit пересоздаст DOM таблиц. В момент
// самой загрузки страницы npTable иногда еще не успевает полностью
// отрисоваться к моменту очередного тика таймера — тогда подсчет "да" по
// неполному набору строк дает временно неверное число, которое на следующем
// тике (когда таблица уже полностью на месте) само исправляется. Раньше
// вспышка запускалась в обоих случаях, из-за чего при загрузке было видно
// "неверное число + вспышка -> верное число + еще одна вспышка". Теперь
// вспышка включается ТОЛЬКО когда пересчет вызван настоящим кликом
// пользователя (triggeredByUserClick === true); фоновые подстраховочные
// пересчеты по таймеру по-прежнему тихо досчитывают правильное число, но
// без визуального эффекта.
function recalcDistrictToggleTotals(triggeredByUserClick, changedColName, changedNewState) {
    const npTable = parentDoc.getElementById("npTable");
    const districtTable = parentDoc.getElementById("districtTable");
    if (!npTable || !districtTable) return;
    if (!npTable.tBodies[0] || !districtTable.tBodies[0]) return;

    const distRows = districtTable.tBodies[0].rows;
    if (distRows.length === 0) return;
    // Строка района — всегда последняя строка в теле districtTable
    // (перед ней может идти строка "Новосибирская область")
    const districtRow = distRows[distRows.length - 1];

    TOGGLE_YES_NO_COLUMNS.forEach(colName => {
        const npColIndex = getColumnIndexByName(npTable, colName);
        const distColIndex = getColumnIndexByName(districtTable, colName);
        if (npColIndex === -1 || distColIndex === -1) return;

        let count = 0;
        Array.from(npTable.tBodies[0].rows).forEach(row => {
            const cell = row.cells[npColIndex];
            if (cell && cell.classList.contains("np-toggle-cell") && cell.dataset.state === "yes") {
                count += 1;
            }
        });

        const distCell = districtRow.cells[distColIndex];
        if (distCell) {
            const newValue = String(count);
            // "Вспышку" запускаем только если значение реально поменялось —
            // recalcDistrictToggleTotals вызывается на каждый клик по любому
            // из трех переключателей и пересчитывает все три колонки сразу,
            // поэтому без этой проверки подсвечивались бы и те ячейки,
            // которые в этот раз не изменились. И только если это настоящий
            // клик пользователя (см. пояснение к параметру выше).
            if (distCell.textContent !== newValue) {
                distCell.textContent = newValue;
                if (triggeredByUserClick) {
                    flashCell(distCell);
                }
            }
        }
    });

    // Строка района (см. цикл выше) пересчитывается "с нуля" — полным
    // подсчетом "да" по видимым в npTable строкам, это корректно и
    // безопасно для повторных (в т.ч. фоновых) вызовов. Для строки ОБЛАСТИ
    // так сделать нельзя: в браузере нет данных по населенным пунктам
    // ОСТАЛЬНЫХ районов области, поэтому ее счетчики можно только точечно
    // поправить на +1/-1 относительно того единственного тумблера, который
    // реально был переключен в этом клике (см. adjustOblastToggleCount).
    // Отсюда и обязательное условие: только если это настоящий клик
    // (triggeredByUserClick) и известны colName/newState этого клика — на
    // фоновых подстраховочных вызовах (colName не передан) ничего не трогаем,
    // иначе счетчик области задваивался/расходился бы на каждый тик таймера.
    if (triggeredByUserClick && changedColName && TOGGLE_YES_NO_COLUMNS.includes(changedColName)) {
        adjustOblastToggleCount(districtTable, changedColName, changedNewState);
    }

    // ==========================================================
    // ОПТИМАЛЬНЫЙ АЛГОРИТМ РАСЧЕТА (см. пояснение по всему проекту
    // ниже, в комментариях к computeNpTableAffordabilitySums и
    // recalcOblastRowAffordabilityAggregates): npTable текущего района
    // перебирается ОДИН РАЗ за клик (а не по разу на district-строку и
    // на область-строку по отдельности) — результат (суммы/счетчики)
    // переиспользуется в обеих функциях ниже.
    // ==========================================================
    const npLevelColIdx = getColumnIndexByName(npTable, "Уровень финансовой доступности");
    const npNeedChangeColIdx = getColumnIndexByName(npTable, "Изменение уровня потребности в развитии дистанционного банковского обслуживания за счет альтернативной инфраструктуры, п.п.");
    const npSums = (npLevelColIdx !== -1 && npNeedChangeColIdx !== -1)
        ? computeNpTableAffordabilitySums(npTable, npLevelColIdx, npNeedChangeColIdx)
        : null;

    // Пересчитываем агрегированные показатели строки района (последняя
    // строка в теле districtTable) — п.1-п.6 из задания на districtRow.
    recalcDistrictRowAffordabilityAggregates(districtTable, districtRow, npSums, triggeredByUserClick);

    // Пересчитываем агрегированные показатели строки области (первая
    // строка в теле districtTable, если она есть) — п.1-п.6 из отдельного
    // задания на oblastRow, с учетом населенных пунктов ВНЕ текущего района.
    recalcOblastRowAffordabilityAggregates(districtTable, npSums, triggeredByUserClick);
}

// =====================================================================
// ИНКРЕМЕНТ/ДЕКРЕМЕНТ СЧЕТЧИКОВ TOGGLE_YES_NO_COLUMNS В СТРОКЕ ОБЛАСТИ
// (districtTable, первая строка в теле таблицы)
// =====================================================================
// В отличие от строки района (которая при каждом клике пересчитывается
// заново — полным подсчетом "да" по видимым в npTable строкам, см. цикл в
// начале recalcDistrictToggleTotals), строку области так пересчитать
// нельзя: она включает населенные пункты ВСЕХ районов области, а в браузере
// на странице конкретного района загружены данные только по ЕГО населенным
// пунктам. Поэтому вместо полного пересчета применяется ТОЧЕЧНАЯ поправка:
// колонка "Количество точек финансового доступа" / "Количество Финансовых
// помощников" / "Количество торговых точек с сервисом ..." в строке области
// увеличивается на 1, если конкретный переключатель в npTable сменился с
// "нет" на "да", и уменьшается на 1, если сменился с "да" на "нет" —
// ровно на ту же единицу, которая только что изменилась в строке района.
// Начальное значение ячейки (до первого клика) — официальный агрегат по
// всей области из NSO_SUMMARY_FILE (см. nso_row_html в Python), от которого
// и ведется этот покликовый инкремент/декремент.
function adjustOblastToggleCount(districtTable, colName, newState) {
    const distRows = districtTable.tBodies[0] ? districtTable.tBodies[0].rows : null;
    // Строка области — первая строка, но только если она реально
    // отрендерена (т.е. есть минимум 2 строки: область + район). Если ее
    // нет (нет данных NSO_SUMMARY_FILE), поправлять нечего.
    if (!distRows || distRows.length < 2) return;
    const oblastRow = distRows[0];

    const colIndex = getColumnIndexByName(districtTable, colName);
    if (colIndex === -1) return;

    const oblastCell = oblastRow.cells[colIndex];
    if (!oblastCell) return;

    const currentCount = parseNumericCellValue(oblastCell.textContent);
    const delta = newState === "yes" ? 1 : -1;
    const newCount = Math.max(0, currentCount + delta);

    oblastCell.textContent = String(newCount);
    // triggeredByUserClick сюда специально не пробрасывается отдельным
    // параметром: adjustOblastToggleCount вызывается ТОЛЬКО из настоящего
    // клика (см. проверку triggeredByUserClick в recalcDistrictToggleTotals
    // перед вызовом этой функции), поэтому вспышка нужна всегда.
    flashCell(oblastCell);
}

// Перебирает ВСЕ строки npTable ОДИН РАЗ и считает величины, нужные сразу
// для обоих пересчетов ниже (строка района и строка области):
//   - levelSum / levelCount — сумма и количество значений "Уровень
//     финансовой доступности" по ВСЕМ строкам (нули не исключаются);
//   - needChangeSum / needChangeCount — сумма и количество ТОЛЬКО
//     ненулевых значений "Изменение уровня потребности...".
// Вынесено в отдельную функцию, чтобы не перебирать npTable дважды
// (для districtRow и для oblastRow отдельно) — см. пояснение в шапке
// recalcOblastRowAffordabilityAggregates про оптимальный алгоритм.
function computeNpTableAffordabilitySums(npTable, npLevelColIdx, npNeedChangeColIdx) {
    const npRows = Array.from(npTable.tBodies[0].rows);
    let levelSum = 0;
    let needChangeSum = 0;
    let needChangeCount = 0;

    npRows.forEach(row => {
        const levelCell = row.cells[npLevelColIdx];
        if (levelCell) levelSum += parseNumericCellValue(levelCell.textContent);

        const needChangeCell = row.cells[npNeedChangeColIdx];
        if (needChangeCell) {
            const val = parseNumericCellValue(needChangeCell.textContent);
            if (val !== 0) {
                needChangeSum += val;
                needChangeCount += 1;
            }
        }
    });

    return { levelSum, levelCount: npRows.length, needChangeSum, needChangeCount };
}

// =====================================================================
// ПЕРЕСЧЕТ АГРЕГИРОВАННЫХ ПОКАЗАТЕЛЕЙ СТРОКИ РАЙОНА (districtTable)
// =====================================================================
// Вызывается из recalcDistrictToggleTotals после пересчета счетчиков "да"
// по TOGGLE_YES_NO_COLUMNS. Пересчитывает в строке района (последняя строка
// в теле districtTable) следующие поля на основе ВСЕХ строк населенных
// пунктов таблицы npTable, относящихся к этому району:
//   1. "Уровень финансовой доступности Старый" — просто текущее значение
//      ячейки districtRow ДО пересчета (используется только внутри этой
//      функции для п.5, отдельной ячейки/колонки под него нет).
//   2. "Изменение уровня потребности в развитии ДБО за счет альтернативной
//      инфраструктуры, п.п." = среднее ненулевых значений этой же колонки
//      по строкам npTable (округление до 1 знака).
//   3. "Уровень финансовой доступности" = среднее арифметическое этой
//      колонки по ВСЕМ строкам npTable (без исключения нулевых, в отличие
//      от п.2 — так задано в требованиях).
//   4. "Уровень потребности в развитии ДБО с учетом альт. инфраструктуры" =
//      100% - "Уровень финансовой доступности" + "Изменение уровня
//      потребности..." (обратите внимание: здесь ПЛЮС, а не минус — это
//      отличается от формулы для отдельного населенного пункта в
//      applyAffordabilityForecastForRow/revertAffordabilityForecastForRow,
//      где вычитается "Бонус"; для строки района формула другая, как прямо
//      указано в задании на эту функцию).
//   5. "Прирост финансовой доступности" = новый "Уровень финансовой
//      доступности" минус "старый" (п.1) — используется только для п.6.
//   6. "Изменение уровня финансовой доступности к предыдущей отчетной
//      дате, п.п." — НАКОПИТЕЛЬНОЕ поле, увеличивается на "Прирост
//      финансовой доступности" (аналогично тому, как это сделано для
//      отдельного населенного пункта).
//
// Форматирование ячеек (проценты с одним знаком после запятой; для полей
// "Изменение..." — стрелка вверх/зеленый при плюсе, вниз/красный при
// минусе, без стрелки при нуле) не меняется — используются те же функции
// setLevelCellValue/setChangeCellValue, что и для строк населенных пунктов.
//
// npSums — уже посчитанные суммы по npTable (см. computeNpTableAffordabilitySums),
// передаются извне, чтобы не перебирать таблицу дважды.
// triggeredByUserClick прокидывается из recalcDistrictToggleTotals и
// определяет, нужна ли визуальная "вспышка" при обновлении ячеек (см.
// пояснение в recalcDistrictToggleTotals про фоновые подстраховочные
// пересчеты по таймеру, которые не должны мигать вспышкой на загрузке
// страницы).
function recalcDistrictRowAffordabilityAggregates(districtTable, districtRow, npSums, triggeredByUserClick) {
    if (!npSums || npSums.levelCount === 0) return;

    const districtCells = getAffordabilityCells(districtTable, districtRow);
    if (!districtCells) return;
    const { levelCell, levelChangeCell, needCell, needChangeCell } = districtCells;

    // --- п.1: "Уровень финансовой доступности Старый" (значение до пересчета) ---
    const oldLevel = parseNumericCellValue(levelCell.textContent);

    // --- п.2: среднее НЕНУЛЕВЫХ значений "Изменение уровня потребности..."
    // по всем населенным пунктам района (округление до 1 знака) ---
    const needChangeAvg = npSums.needChangeCount > 0
        ? Math.round((npSums.needChangeSum / npSums.needChangeCount) * 10) / 10
        : 0;

    // --- п.3: среднее арифметическое "Уровня финансовой доступности" по
    // ВСЕМ населенным пунктам района (нулевые значения здесь НЕ исключаются,
    // в отличие от п.2 — так задано в требованиях) ---
    const newLevel = Math.round((npSums.levelSum / npSums.levelCount) * 10) / 10;

    // --- п.4: "Уровень потребности..." = 100% - Уровень + Изменение уровня
    // потребности (обратите внимание на знак "+", см. пояснение в шапке
    // функции). Math.max(0, ...) — защитный "пол" от ухода в минус, в
    // задании явно не оговорен, но предотвращает отрицательные проценты. ---
    const needLevel = Math.max(0, 100 - newLevel + needChangeAvg);

    // --- п.5: "Прирост финансовой доступности" ---
    const levelGain = newLevel - oldLevel;

    // !!triggeredByUserClick — важно явно привести к boolean (true/false), а
    // не передавать triggeredByUserClick как есть: если он undefined (фоновый
    // вызов из setInterval, где параметр вообще не передается), JS-параметр
    // со значением по умолчанию "shouldFlash = true" в setLevelCellValue/
    // setChangeCellValue сработал бы именно на undefined и включил бы
    // вспышку — что и является тем самым глюком, который мы чинили ранее.
    const shouldFlash = !!triggeredByUserClick;

    // --- Обновляем "Уровень финансовой доступности" строки района ---
    setLevelCellValue(levelCell, newLevel, shouldFlash);

    // --- п.6: "Изменение уровня фин. доступности к пред. отчетной дате,
    // п.п." — накопительно, += Прирост ---
    const prevLevelChange = parseNumericCellValue(levelChangeCell.textContent);
    setChangeCellValue(levelChangeCell, prevLevelChange + levelGain, shouldFlash);

    // --- Обновляем "Уровень потребности в развитии ДБО..." (строка района).
    // applyNeedLevelFill = true — ДОБАВЛЕНО по отдельному заданию: заливаем
    // фон ячейки цветом по порогам get_need_level_class/getNeedLevelClassJS
    // (см. пояснение к параметру в setLevelCellValue выше). ---
    setLevelCellValue(needCell, needLevel, shouldFlash, true);

    // --- Обновляем "Изменение уровня потребности..." значением, посчитанным в п.2 ---
    setChangeCellValue(needChangeCell, needChangeAvg, shouldFlash);
}

// =====================================================================
// ПЕРЕСЧЕТ АГРЕГИРОВАННЫХ ПОКАЗАТЕЛЕЙ СТРОКИ ОБЛАСТИ (districtTable, ПЕРВАЯ
// строка в теле таблицы — "Новосибирская область")
// =====================================================================
// Формулы полностью аналогичны recalcDistrictRowAffordabilityAggregates
// (п.1-п.6 в том же порядке), но считаются не по населенным пунктам ОДНОГО
// района, а по ВСЕМ населенным пунктам области — т.е. по всему файлу
// NP_FILE = DB{date}_NP.xlsx, с одной важной оговоркой из задания:
// для населенных пунктов ТЕКУЩЕГО (открытого) района нужно брать актуальные
// (пересчитанные с учетом действий пользователя) значения из npTable, а не
// исходные значения из файла.
//
// >>> ОПТИМАЛЬНЫЙ АЛГОРИТМ (обоснование выбора) <<<
// Файл NP_FILE может содержать тысячи населенных пунктов по всей области.
// Пересчитывать сумму/среднее по ВСЕМ ним заново при КАЖДОМ клике
// пользователя (а кликов может быть много подряд) — плохая идея: это O(N)
// тяжелых операций (парсинг чисел из тысяч ячеек) на каждый клик, тогда как
// реально от клика меняются данные только по населенным пунктам ТЕКУЩЕГО
// района (их обычно от единиц до нескольких десятков).
// Поэтому расчет разбит на две части:
//   1) "Остальная область" (все населенные пункты ВНЕ текущего района) —
//      их значения в файле НЕ меняются действиями пользователя на этой
//      странице, поэтому суммы/счетчики по ним считаются ОДИН РАЗ в Python
//      при загрузке страницы, с кэшированием через st.cache_data (см.
//      compute_other_districts_affordability_aggregates в начале файла), и
//      передаются в браузер один раз через
//      window.parent.__oblastOtherAggregates (JSON, установленный отдельным
//      components.html-скриптом непосредственно на странице района).
//   2) "Текущий район" — его населенные пункты как раз меняются кликами,
//      поэтому их сумма пересчитывается в браузере при каждом клике, но
//      ОДНИМ проходом по строкам npTable (computeNpTableAffordabilitySums,
//      вызывается один раз в recalcDistrictToggleTotals и передается сюда
//      через параметр npSums — код ниже НЕ перебирает npTable повторно).
// Итоговое среднее по всей области получается простым объединением двух
// частичных сумм: (сумма_вне_района + сумма_района) / (кол-во_вне_района +
// кол-во_района). Стоимость пересчета на каждый клик — O(размер текущего
// района), а не O(размер всей области), независимо от того, сколько всего
// населенных пунктов в NP_FILE.
function recalcOblastRowAffordabilityAggregates(districtTable, npSums, triggeredByUserClick) {
    if (!npSums) return;

    const distRows = districtTable.tBodies[0] ? districtTable.tBodies[0].rows : null;
    // Строка области — первая строка в теле districtTable, но только если
    // она реально есть (т.е. строк минимум 2: область + район). Если строка
    // области не была отрендерена (например, нет данных NSO_SUMMARY_FILE),
    // districtTable.tBodies[0].rows[0] был бы строкой РАЙОНА — пересчитывать
    // ее по формулам области было бы ошибкой, поэтому в этом случае просто
    // ничего не делаем.
    if (!distRows || distRows.length < 2) return;
    const oblastRow = distRows[0];

    const oblastCells = getAffordabilityCells(districtTable, oblastRow);
    if (!oblastCells) return;
    const { levelCell, levelChangeCell, needCell, needChangeCell } = oblastCells;

    // Кэшированные (посчитанные в Python при загрузке страницы) суммы по
    // населенным пунктам ВНЕ текущего района. Если по какой-то причине их
    // нет (страница открыта не через штатный маршрут, скрипт не успел
    // отработать и т.п.) — считаем область "равной" текущему району, чтобы
    // не сломать расчет полностью.
    const rawOther = window.parent.__oblastOtherAggregates;
    const other = (rawOther && typeof rawOther === "object")
        ? rawOther
        : { otherLevelSum: 0, otherLevelCount: 0, otherNeedChangeSum: 0, otherNeedChangeCount: 0 };

    // --- п.1: "Уровень финансовой доступности Старый" ---
    const oldLevel = parseNumericCellValue(levelCell.textContent);

    // --- п.3: "Уровень финансовой доступности" по ВСЕЙ области = среднее
    // (сумма вне района + сумма по району) / (кол-во вне района + кол-во по району) ---
    const totalLevelSum = other.otherLevelSum + npSums.levelSum;
    const totalLevelCount = other.otherLevelCount + npSums.levelCount;
    const newLevel = totalLevelCount > 0
        ? Math.round((totalLevelSum / totalLevelCount) * 10) / 10
        : oldLevel;

    // --- п.2: "Изменение уровня потребности..." по ВСЕЙ области = среднее
    // ненулевых значений (вне района + по району) ---
    const totalNeedChangeSum = other.otherNeedChangeSum + npSums.needChangeSum;
    const totalNeedChangeCount = other.otherNeedChangeCount + npSums.needChangeCount;
    const needChangeAvg = totalNeedChangeCount > 0
        ? Math.round((totalNeedChangeSum / totalNeedChangeCount) * 10) / 10
        : 0;

    // --- п.4: "Уровень потребности..." = 100% - Уровень + Изменение уровня потребности ---
    const needLevel = Math.max(0, 100 - newLevel + needChangeAvg);

    // --- п.5: "Прирост финансовой доступности" ---
    const levelGain = newLevel - oldLevel;

    const shouldFlash = !!triggeredByUserClick;

    // --- Обновляем "Уровень финансовой доступности" строки области ---
    setLevelCellValue(levelCell, newLevel, shouldFlash);

    // --- п.6: накопительно, += Прирост ---
    const prevLevelChange = parseNumericCellValue(levelChangeCell.textContent);
    setChangeCellValue(levelChangeCell, prevLevelChange + levelGain, shouldFlash);

    // --- Обновляем "Уровень потребности в развитии ДБО..." (строка области).
    // applyNeedLevelFill = true — ДОБАВЛЕНО по отдельному заданию: заливаем
    // фон ячейки цветом по порогам get_need_level_class/getNeedLevelClassJS
    // (см. пояснение к параметру в setLevelCellValue выше). ---
    setLevelCellValue(needCell, needLevel, shouldFlash, true);

    // --- Обновляем "Изменение уровня потребности..." значением из п.2 ---
    setChangeCellValue(needChangeCell, needChangeAvg, shouldFlash);
}


// =====================================================================
// ПРОГНОЗНЫЙ ПЕРЕСЧЕТ УРОВНЯ ФИН. ДОСТУПНОСТИ И ПОТРЕБНОСТИ В ДБО (npTable)
// =====================================================================
// При переключении "да/нет" в колонках TOGGLE_YES_NO_COLUMNS для конкретного
// населенного пункта (строки npTable) дополнительно пересчитываются:
//   - "Уровень финансовой доступности" (п.1, п.2 задания)
//   - "Изменение уровня финансовой доступности к предыдущей отчетной дате, п.п."
//     (п.7 задания — значение НАКОПИТЕЛЬНОЕ, прибавляется к уже показанному)
//   - "Уровень потребности в развитии дистанционного банковского обслуживания
//     с учетом альтернативной инфраструктуры" (п.5 задания)
//   - "Изменение уровня потребности в развитии дистанционного банковского
//     обслуживания за счет альтернативной инфраструктуры, п.п." (п.6 задания)
//
// ОБНОВЛЕНО: изначально в задании все правила были сформулированы только
// для направления "нет" -> "да" (см. историю в комментариях ниже к каждому
// пункту). По отдельному запросу заказчика добавлен СИММЕТРИЧНЫЙ ОТКАТ при
// обратном переключении ("да" -> "нет") — см. блок "ОТКАТ ПРОГНОЗНОГО
// ПЕРЕСЧЕТА" ниже, сразу после applyAffordabilityForecastForRow. Чтобы откат
// был математически точным (а не просто "пересчитать заново по формуле",
// что могло бы разойтись со значением на экране из-за ограничения уровня в
// 100% или порядка последовательных кликов по разным колонкам), в момент
// начисления (applyAffordabilityForecastForRow) величина фактически
// начисленного прироста и бонуса сохраняется в data-атрибуте строки
// (см. getAffordabilityAppliedState/setAffordabilityAppliedState), а при
// откате вычитается РОВНО ТА ЖЕ величина, что была прибавлена.

// Прибавка к "Уровню финансовой доступности" при переключении колонки в "да"
// (п.1 — 5%, п.2 — 18.5%). У "Количество Финансовых помощников" прибавки к
// уровню нет — она участвует только в расчете "Бонуса" (см. ниже).
const AFFORDABILITY_LEVEL_DELTA = {
    'Количество точек финансового доступа': 5,
    'Количество торговых точек с сервисом "Выдача наличных на кассе"': 18.5,
};

// Таблица "Бонуса" (п.4): диапазон "Уровня финансовой доступности" (ПОСЛЕ
// прибавки по п.1/п.2 текущего клика) -> прибавка за добавленную
// "Количество точек финансового доступа" (pointBonus) и за добавленную
// "Количество Финансовых помощников" (helperBonus). "Количество торговых
// точек ..." в расчете Бонуса не участвует (в задании для нее бонус не
// определен — только прибавка к уровню, см. п.2).
const AFFORDABILITY_BONUS_TABLE = [
    { maxExclusive: 31,       pointBonus: 4, helperBonus: 6 }, // п.4.1: 0 – <31%
    { maxExclusive: 46,       pointBonus: 3, helperBonus: 5 }, // п.4.2: 31 – <46%
    { maxExclusive: 66,       pointBonus: 2, helperBonus: 4 }, // п.4.3: 46 – <66%
    { maxExclusive: 86,       pointBonus: 1, helperBonus: 3 }, // п.4.4: 66 – <86%
    { maxExclusive: Infinity, pointBonus: 0, helperBonus: 2 }, // п.4.5: 86 – 100%
];

function getAffordabilityBonusRates(levelPercent) {
    for (const bracket of AFFORDABILITY_BONUS_TABLE) {
        if (levelPercent < bracket.maxExclusive) return bracket;
    }
    return AFFORDABILITY_BONUS_TABLE[AFFORDABILITY_BONUS_TABLE.length - 1];
}

// Извлекает число из текста ячейки вида "85.0%", "⬆ +3.0", "⬇ -2.0", "0.0"
function parseNumericCellValue(text) {
    if (!text) return 0;
    const match = String(text).replace(/,/g, ".").match(/[+-]?\\d+(\\.\\d+)?/);
    return match ? parseFloat(match[0]) : 0;
}

// Длительность CSS-анимации вспышки в миллисекундах — ДОЛЖНА совпадать с
// "1.0s" в правиле "animation: cellValueFlash 1.0s ease-out;" (см. CSS выше
// по файлу). Используется в setLevelCellValue, чтобы отложенно применить
// заливку .need-level-* ровно к моменту завершения вспышки (см. пояснение
// там же).
const VALUE_FLASH_DURATION_MS = 1000;

// Короткая цветовая "вспышка" на ячейке (см. @keyframes cellValueFlash в CSS
// выше по файлу) — чтобы пересчитанное значение было заметно визуально, а не
// только "тихо" менялось в тексте. Класс сначала снимается, затем (после
// принудительного reflow через чтение offsetWidth) добавляется заново —
// иначе при повторном срабатывании подряд на той же ячейке анимация CSS не
// перезапускается браузером.
function flashCell(cell) {
    if (!cell) return;
    cell.classList.remove("value-flash");
    void cell.offsetWidth;
    cell.classList.add("value-flash");
}

// JS-аналог Python-функции get_need_level_class(col_name, num_val) (см. ее
// определение в начале файла) — используется ТОЛЬКО для ячейки "Уровень
// потребности в развитии дистанционного банковского обслуживания с учетом
// альтернативной инфраструктуры" в строках области/района districtTable
// (по отдельному заданию), поэтому параметр col_name здесь не нужен: эта
// функция вызывается лишь там, где заливка точно требуется. Пороги и
// названия классов — 1-в-1 как в Python-версии и как в CSS-правилах
// .need-level-0-10 / .need-level-11-15 / .need-level-16-20 /
// .need-level-21-30 / .need-level-31-100 (см. блок "3. СТИЛИ ТАБЛИЦ" выше).
function getNeedLevelClassJS(numVal) {
    const rounded = Math.round(numVal * 100) / 100; // округление до 2 знаков, как Python round(num_val, 2)
    if (rounded >= 0 && rounded < 11) return "need-level-0-10";
    if (rounded >= 11 && rounded < 16) return "need-level-11-15";
    if (rounded >= 16 && rounded < 21) return "need-level-16-20";
    if (rounded >= 21 && rounded < 31) return "need-level-21-30";
    if (rounded >= 31) return "need-level-31-100";
    return ""; // теоретически недостижимо для num_val >= 0, оставлено для защиты от отрицательных значений
}

// Записывает новое значение в проценто-ячейку без стрелки: "Уровень
// финансовой доступности" / "Уровень потребности в развитии ДБО ...".
// shouldFlash (по умолчанию true) — запускать ли визуальную "вспышку"
// (flashCell). По умолчанию true, т.к. существующие вызовы этой функции
// (из applyAffordabilityForecastForRow / revertAffordabilityForecastForRow)
// всегда происходят в ответ на настоящий клик пользователя. Параметр
// добавлен для recalcDistrictRowAffordabilityAggregates, которая вызывается
// в том числе из фоновых подстраховочных пересчетов по таймеру — там
// вспышка должна быть отключена (см. пояснение в recalcDistrictToggleTotals).
// applyNeedLevelFill (по умолчанию false) — ДОБАВЛЕНО по отдельному заданию:
// если true, класс ячейки вычисляется через getNeedLevelClassJS(numVal)
// (заливка фона по тем же порогам, что и в Python get_need_level_class),
// иначе класс всегда пустой — как и раньше, и как при первичном рендере
// этой же колонки в npTable (там get_need_level_class всегда возвращает ""
// для этого column-имени, заливка нужна только в districtTable по строкам
// области/района — см. вызовы этой функции с applyNeedLevelFill=true в
// recalcDistrictRowAffordabilityAggregates/recalcOblastRowAffordabilityAggregates).
// ВАЖНО: анимация вспышки (@keyframes cellValueFlash) висит прямо на фоне
// td.value-flash, поэтому конкурировать с !important-заливкой .need-level-*
// напрямую (той же самой анимацией) бессмысленно — !important внутри
// @keyframes браузеры по спецификации CSS игнорируют, а обычная (без
// !important) анимация background-color в любом случае имеет более низкий
// приоритет в каскаде, чем !important-правило .need-level-*.
// Решение — ОЧЕРЕДНОСТЬ, а не слои: если applyNeedLevelFill=true и вспышка
// нужна (shouldFlash=true), заливка временно НЕ применяется — className на
// время анимации остается пустым, поэтому анимация background-color ничем
// не перебивается и полностью видна, — а класс .need-level-* навешивается
// уже ПОСЛЕ того как вспышка отыграла (через setTimeout на
// VALUE_FLASH_DURATION_MS, синхронизированный с длительностью CSS-анимации).
// Визуально получается ровно "сначала мигнули красным, потом залилось
// цветом". Если вспышка не нужна (shouldFlash=false — например, фоновый
// подстраховочный пересчет по таймеру) или заливка не нужна вовсе —
// класс применяется сразу, без всякой отсрочки.
function setLevelCellValue(cell, numVal, shouldFlash = true, applyNeedLevelFill = false) {
    if (!cell) return;
    cell.textContent = numVal.toFixed(1) + "%";

    const needLevelClass = applyNeedLevelFill ? getNeedLevelClassJS(numVal) : "";

    if (applyNeedLevelFill && shouldFlash) {
        cell.className = ""; // на время вспышки заливки быть не должно
        flashCell(cell);
        setTimeout(() => {
            cell.className = needLevelClass;
        }, VALUE_FLASH_DURATION_MS);
    } else {
        cell.className = needLevelClass;
        if (shouldFlash) flashCell(cell);
    }
}

// Записывает новое значение в ячейку "Изменение уровня ..., п.п." с той же
// цветовой логикой, что и при первичном рендере в Python (см. "ДОБАВЛЕННЫЙ
// БЛОК" в блоке формирования district_table_html / np_table_html ниже по
// файлу): положительное — зеленым со стрелкой вверх, отрицательное —
// красным со стрелкой вниз, ноль — без стрелки и без особого цвета.
// shouldFlash — см. пояснение к этому же параметру в setLevelCellValue выше.
function setChangeCellValue(cell, numVal, shouldFlash = true) {
    if (!cell) return;
    const rounded = Math.round(numVal * 10) / 10; // округление до 1 знака, как python ":.1f"
    let cssClass = "";
    let arrow = "";
    let formatted = "0.0";
    if (rounded > 0) {
        cssClass = "change-pos-custom";
        arrow = "&#11014;";
        formatted = "+" + rounded.toFixed(1);
    } else if (rounded < 0) {
        cssClass = "change-neg-custom";
        arrow = "&#11015;";
        formatted = rounded.toFixed(1);
    }
    cell.className = cssClass;
    cell.innerHTML = arrow + " " + formatted;
    if (shouldFlash) flashCell(cell);
}

// Находит все 4 ячейки, с которыми работает пересчет, для данной строки
// npTable. Вынесено в отдельную функцию, т.к. используется и при начислении
// (applyAffordabilityForecastForRow), и при откате
// (revertAffordabilityForecastForRow) — чтобы не дублировать один и тот же
// поиск колонок дважды.
function getAffordabilityCells(npTable, row) {
    const levelColIdx = getColumnIndexByName(npTable, "Уровень финансовой доступности");
    const levelChangeColIdx = getColumnIndexByName(npTable, "Изменение уровня финансовой доступности к предыдущей отчетной дате, п.п.");
    const needColIdx = getColumnIndexByName(npTable, "Уровень потребности в развитии дистанционного банковского обслуживания с учетом альтернативной инфраструктуры");
    const needChangeColIdx = getColumnIndexByName(npTable, "Изменение уровня потребности в развитии дистанционного банковского обслуживания за счет альтернативной инфраструктуры, п.п.");
    if (levelColIdx === -1 || levelChangeColIdx === -1 || needColIdx === -1 || needChangeColIdx === -1) return null;

    const levelCell = row.cells[levelColIdx];
    const levelChangeCell = row.cells[levelChangeColIdx];
    const needCell = row.cells[needColIdx];
    const needChangeCell = row.cells[needChangeColIdx];
    if (!levelCell || !levelChangeCell || !needCell || !needChangeCell) return null;

    return { levelCell, levelChangeCell, needCell, needChangeCell };
}

// Читает/пишет "журнал начислений" по строке — сколько именно (levelGain,
// bonusGain) было прибавлено по каждой из колонок TOGGLE_YES_NO_COLUMNS в
// момент последнего включения ("нет" -> "да"). Именно эти сохраненные
// значения используются при обратном переключении, чтобы откат был точным.
function getAffordabilityAppliedState(row) {
    if (!row.dataset.affordabilityApplied) return {};
    try {
        return JSON.parse(row.dataset.affordabilityApplied) || {};
    } catch (e) {
        return {};
    }
}
function setAffordabilityAppliedState(row, state) {
    row.dataset.affordabilityApplied = JSON.stringify(state);
}

// Основной пересчет (п.0–п.7 задания) для ОДНОЙ строки npTable — вызывается
// из initNpToggles сразу после того, как пользователь переключил "нет" -> "да"
// в одной из колонок TOGGLE_YES_NO_COLUMNS для этого населенного пункта.
// За откат обратного переключения ("да" -> "нет") отвечает отдельная функция
// revertAffordabilityForecastForRow сразу ниже.
function applyAffordabilityForecastForRow(npTable, row, colName) {
    const cells = getAffordabilityCells(npTable, row);
    if (!cells) return;
    const { levelCell, levelChangeCell, needCell, needChangeCell } = cells;

    // Защита от повторного начисления: если по этой колонке в этой строке
    // эффект уже применен (запись есть в "журнале"), повторно ничего не
    // начисляем — иначе накопительные поля (п.7) задвоились бы.
    const appliedState = getAffordabilityAppliedState(row);
    if (appliedState[colName]) return;

    // --- п.0: "Уровень финансовой доступности Старый" ---
    const oldLevel = parseNumericCellValue(levelCell.textContent);

    // --- п.1, п.2: прибавка к уровню финансовой доступности (не выше 100%) ---
    const levelDelta = AFFORDABILITY_LEVEL_DELTA[colName] || 0;
    const newLevel = Math.min(100, oldLevel + levelDelta);

    // --- п.3: "Прирост финансовой доступности" ---
    const levelGain = newLevel - oldLevel;

    // --- п.4: "Бонус" — накопительный, хранится в data-атрибуте строки
    // (в самой таблице отдельной колонки для него нет, он используется
    // только для расчета двух полей "Уровень/Изменение уровня потребности...")
    const bonusRates = getAffordabilityBonusRates(newLevel);
    let bonusGain = 0;
    if (colName === "Количество точек финансового доступа") {
        bonusGain = bonusRates.pointBonus;
    } else if (colName === "Количество Финансовых помощников") {
        bonusGain = bonusRates.helperBonus;
    }

    // Запоминаем в "журнале", сколько именно было начислено по этой колонке —
    // ЭТО и есть основа для точного симметричного отката при выключении.
    appliedState[colName] = { levelGain, bonusGain };
    setAffordabilityAppliedState(row, appliedState);

    const bonusTotal = parseFloat(row.dataset.affordabilityBonus || "0") + bonusGain;
    row.dataset.affordabilityBonus = String(bonusTotal);

    // --- Обновляем "Уровень финансовой доступности" ---
    setLevelCellValue(levelCell, newLevel);

    // --- п.7: "Изменение уровня фин. доступности к пред. отчетной дате, п.п." (накопительно) ---
    const prevLevelChange = parseNumericCellValue(levelChangeCell.textContent);
    setChangeCellValue(levelChangeCell, prevLevelChange + levelGain);

    // --- п.5: "Уровень потребности в развитии ДБО с учетом альт. инфраструктуры" ---
    // Math.max(0, ...) — защитный "пол", в задании не оговорен явно, но
    // предотвращает уход в отрицательные проценты, если Бонус окажется
    // больше остатка (100 - Уровень).
    const needLevel = Math.max(0, 100 - newLevel - bonusTotal);
    setLevelCellValue(needCell, needLevel);

    // --- п.6: "Изменение уровня потребности ... за счет альт. инфраструктуры, п.п." ---
    setChangeCellValue(needChangeCell, -bonusTotal);
}

// =====================================================================
// ОТКАТ ПРОГНОЗНОГО ПЕРЕСЧЕТА ПРИ ОБРАТНОМ ПЕРЕКЛЮЧЕНИИ ("да" -> "нет")
// =====================================================================
// Отдельный, локализованный кусок кода (по запросу заказчика): при
// выключении тумблера в одной из колонок TOGGLE_YES_NO_COLUMNS полностью
// СИММЕТРИЧНО отменяется эффект, ранее начисленный ЭТОЙ ЖЕ колонкой этой же
// строке функцией applyAffordabilityForecastForRow выше.
//
// Принцип отката: НЕ пересчитываем формулы заново "с нуля" (это могло бы
// разойтись с тем, что реально показано на экране — например, из-за
// ограничения уровня в 100%, которое могло "срезать" фактически начисленный
// прирост), а вычитаем ровно ту величину (levelGain/bonusGain), которая была
// сохранена в "журнале начислений" (getAffordabilityAppliedState) в момент
// включения этой же колонки.
//
// Если по этой колонке в этой строке ничего не было начислено (тумблер
// выключали, ни разу не включив, либо эффект уже был отменен ранее) —
// откатывать нечего, функция ничего не делает.
function revertAffordabilityForecastForRow(npTable, row, colName) {
    const appliedState = getAffordabilityAppliedState(row);
    const applied = appliedState[colName];
    if (!applied) return; // нечего откатывать

    const cells = getAffordabilityCells(npTable, row);
    if (!cells) return;
    const { levelCell, levelChangeCell, needCell, needChangeCell } = cells;

    // --- Откат п.1/п.2: вычитаем ровно тот прирост уровня, что был начислен ---
    const oldLevel = parseNumericCellValue(levelCell.textContent);
    const newLevel = Math.min(100, Math.max(0, oldLevel - applied.levelGain));

    // --- Откат п.4: вычитаем ровно тот бонус, что был начислен этой колонкой ---
    const bonusTotal = Math.max(0, parseFloat(row.dataset.affordabilityBonus || "0") - applied.bonusGain);
    row.dataset.affordabilityBonus = String(bonusTotal);

    // Запись об этой колонке в "журнале" больше не актуальна: при следующем
    // включении эффект будет посчитан заново, исходя из уровня на тот момент.
    delete appliedState[colName];
    setAffordabilityAppliedState(row, appliedState);

    // --- Обновляем "Уровень финансовой доступности" ---
    setLevelCellValue(levelCell, newLevel);

    // --- Откат п.7: из накопленного "Изменения уровня фин. доступности к
    // пред. отчетной дате, п.п." вычитаем ровно тот прирост, что был в него
    // добавлен при включении этой колонки ---
    const prevLevelChange = parseNumericCellValue(levelChangeCell.textContent);
    setChangeCellValue(levelChangeCell, prevLevelChange - applied.levelGain);

    // --- п.5, п.6 пересчитываются от уже обновленных newLevel/bonusTotal —
    // это не "пересчет с нуля", а прямое следствие формул из задания,
    // поэтому расхождений с applyAffordabilityForecastForRow не возникает ---
    const needLevel = Math.max(0, 100 - newLevel - bonusTotal);
    setLevelCellValue(needCell, needLevel);

    setChangeCellValue(needChangeCell, -bonusTotal);
}

// Диспетчер: вызывается из initNpToggles при любом переключении тумблера в
// npTable и направляет выполнение либо в начисление (applyAffordabilityForecastForRow),
// либо в симметричный откат (revertAffordabilityForecastForRow) — в
// зависимости от направления переключения.
function syncAffordabilityForecastForRow(npTable, row, colName, newState) {
    if (newState === "yes") {
        applyAffordabilityForecastForRow(npTable, row, colName);
    } else {
        revertAffordabilityForecastForRow(npTable, row, colName);
    }
}


// Обработчик клика вешается ОДИН РАЗ на parentDoc (а не на каждую кнопку),
// поэтому переключатель продолжает работать даже после того, как Streamlit
// перерисовывает HTML-блок с таблицей (например, при любом ререндере страницы),
// из-за чего обработчики, навешенные напрямую на кнопки, слетают вместе со
// старыми DOM-узлами.
function initNpToggles() {
    if (parentDoc.__npToggleDelegated === true) return;
    parentDoc.__npToggleDelegated = true;

    parentDoc.addEventListener("click", function (e) {
        const upBtn = e.target.closest("#npTable td.np-toggle-cell .toggle-arrow-up");
        const downBtn = e.target.closest("#npTable td.np-toggle-cell .toggle-arrow-down");
        if (!upBtn && !downBtn) return;

        e.preventDefault();
        e.stopPropagation();

        const cell = (upBtn || downBtn).closest("td.np-toggle-cell");
        if (!cell) return;
        const valueSpan = cell.querySelector(".toggle-value");
        const newState = upBtn ? "yes" : "no";

        if (cell.dataset.state !== newState) {
            cell.dataset.state = newState;
            if (valueSpan) valueSpan.textContent = newState === "yes" ? "да" : "нет";

            // Определяем имя колонки этой ячейки (по data-colname заголовка
            // на том же индексе) — используется и для прогнозного пересчета
            // "Уровня финансовой доступности" (см. ниже), и для инкремента/
            // декремента счетчика строки области (см. recalcDistrictToggleTotals
            // -> adjustOblastToggleCount).
            const npTable = cell.closest("table#npTable");
            const row = cell.closest("tr");
            let colName = null;
            if (npTable && row) {
                const colIndex = Array.from(row.cells).indexOf(cell);
                const headerCell = npTable.tHead && npTable.tHead.rows[0]
                    ? npTable.tHead.rows[0].cells[colIndex]
                    : null;
                colName = headerCell ? headerCell.dataset.colname : null;

                // Прогнозный пересчет "Уровня финансовой доступности" и
                // связанных полей для этой строки — как при включении
                // ("нет" -> "да", начисление, applyAffordabilityForecastForRow),
                // так и при выключении ("да" -> "нет", симметричный откат,
                // revertAffordabilityForecastForRow). Направление определяет
                // диспетчер syncAffordabilityForecastForRow (см. выше по файлу).
                if (colName && TOGGLE_YES_NO_COLUMNS.includes(colName)) {
                    syncAffordabilityForecastForRow(npTable, row, colName, newState);
                }
            }

            // triggeredByUserClick = true — это настоящий клик пользователя,
            // поэтому изменившиеся ячейки districtTable подсвечиваются
            // вспышкой (см. пояснение к параметру в recalcDistrictToggleTotals).
            // colName/newState передаются дополнительно, чтобы
            // recalcDistrictToggleTotals могла инкрементировать/декрементировать
            // счетчик именно этой колонки в строке области (см.
            // adjustOblastToggleCount) — в отличие от строки района, для
            // строки области это не пересчет "с нуля", а точечная поправка
            // на +1/-1 относительно исходного значения, т.к. живых данных по
            // остальным районам области в браузере нет.
            recalcDistrictToggleTotals(true, colName, newState);
        }
    });
}

// =====================================================================
// ФИКСАЦИЯ ТАБЛИЦЫ districtTable ПРИ СКРОЛЛЕ (страница 4, "СЦЕНАРИЙ №4")
// =====================================================================
// История двух неудачных попыток и в чем была причина:
//   1) position: sticky на th/tr/td по отдельности — несколько sticky-
//      элементов с одинаковым top "прилипают" к одной линии независимо
//      друг от друга, и строки таблицы просто накладываются друг на друга.
//   2) position: sticky на ОДНОМ элементе-обертке вокруг всей таблицы —
//      технически правильный CSS-подход, но не сработал, т.к. где-то по
//      цепочке предков этого враппера Streamlit создает элемент, который
//      обрезает/ограничивает sticky-контекст (это особенность внутренней
//      верстки Streamlit на flex-контейнерах, и без инспекции в браузере
//      заранее не угадать, какой именно предок виноват).
//
// Поэтому фиксация теперь полностью реализована на JS через position: fixed,
// но с важным отличием от самой первой JS-попытки: тогда обработчик scroll
// был навешен на window.parent, а событие scroll НЕ ВСПЛЫВАЕТ (не bubbles) —
// если реальная прокрутка происходит на каком-то внутреннем div, событие
// scroll этого div никогда не долетит до window. Решение — навесить
// обработчик scroll в РЕЖИМЕ ПЕРЕХВАТА (capture phase, третий аргумент
// addEventListener = true): в отличие от всплытия, фаза перехвата всегда
// проходит "сверху вниз" от document ко всем вложенным элементам, поэтому
// такой обработчик сработает при скролле ЛЮБОГО элемента на странице,
// включая произвольный вложенный div, независимо от того, что именно
// физически прокручивается внутри разметки Streamlit.
//
// Второй важный момент: чтобы понять, когда таблицу нужно зафиксировать
// и когда вернуть обратно, используется getBoundingClientRect() — этот
// метод всегда возвращает координаты элемента ОТНОСИТЕЛЬНО ВИДИМОЙ ОБЛАСТИ
// (viewport), независимо от того, какой контейнер скроллится. Поэтому нет
// нужды заранее знать, что именно является "скролл-контейнером" — можно
// просто проверять текущее положение таблицы (когда она в обычном потоке)
// и положение плейсхолдера (когда она уже зафиксирована).

const STICKY_SCROLL_THRESHOLD = -20; // «до верха страницы осталось 20 пикселей»

let districtTableRef = null;          // ссылка на текущий DOM-узел таблицы
let districtTableFixed = false;       // зафиксирована ли таблица сейчас
let districtTablePlaceholder = null;  // "заглушка" на месте таблицы, пока она fixed

function resetDistrictTableInlineStyles(table) {
    table.style.removeProperty("position");
    table.style.removeProperty("top");
    table.style.removeProperty("left");
    table.style.removeProperty("width");
    table.style.removeProperty("z-index");
    table.style.removeProperty("box-shadow");
    table.style.removeProperty("background-color");
}

// Применяет фиксированное положение/размеры таблицы. Важно: глобальное
// правило "table {{ width: 100% !important; }}" (см. блок "3. СТИЛИ ТАБЛИЦ")
// перебивает обычный инлайн-стиль width, заданный через table.style.width —
// !important в подключенной таблице стилей побеждает обычный инлайн-стиль.
// Пока таблица в обычном потоке документа, "width: 100%" считается от ее
// родителя — это то, что нужно. Но как только таблица становится
// position: fixed, точкой отсчета для "100%" становится viewport, а не
// исходный родитель, из-за чего таблица растягивается и "уезжает" вправо
// (это и происходило на скриншоте: было бы 1760px, а по факту растягивалась
// на всю ширину viewport, потому что !important-правило игнорировало
// заданный нами инлайн width). Решение — задавать width (и left, на всякий
// случай) с приоритетом "important" через setProperty, чтобы наш инлайн-
// стиль тоже стал !important и гарантированно победил.
function applyDistrictTableFixedBox(table, left, width) {
    table.style.setProperty("position", "fixed", "important");
    table.style.setProperty("top", "-16px", "important");
    table.style.setProperty("left", left + "px", "important");
    table.style.setProperty("width", width + "px", "important");
    table.style.setProperty("z-index", "600", "important");
    table.style.setProperty("box-shadow", "0 4px 12px rgba(0,0,0,0.18)", "important");
    table.style.setProperty("background-color", "#ffffff", "important");
}

function syncDistrictTableSticky() {
    const table = parentDoc.getElementById("districtTable");
    if (!table) return; // на этой странице (не "СЦЕНАРИЙ №4") таблицы просто нет

    // Streamlit мог пересоздать DOM-узел таблицы — начинаем отслеживание заново.
    if (table !== districtTableRef) {
        districtTableRef = table;
        districtTableFixed = false;
        districtTablePlaceholder = null;
        resetDistrictTableInlineStyles(table);
    }

    // Плейсхолдер занимает место таблицы в потоке документа, пока сама
    // таблица находится в position: fixed (иначе контент под ней "прыгнет" вверх).
    if (!districtTablePlaceholder || !districtTablePlaceholder.isConnected) {
        districtTablePlaceholder = parentDoc.createElement("div");
        districtTablePlaceholder.id = "districtTablePlaceholder";
        districtTablePlaceholder.style.display = "none";
        table.parentNode.insertBefore(districtTablePlaceholder, table);
    }

    if (!districtTableFixed) {
        // Таблица в обычном потоке — просто смотрим, насколько близко ее
        // верхний край подошел к верхней границе видимой области (viewport).
        const rect = table.getBoundingClientRect();
        if (rect.top <= STICKY_SCROLL_THRESHOLD) {
            // Запоминаем текущие размеры/положение ДО перехода в fixed,
            // чтобы таблица не "прыгнула" по ширине, выйдя из потока документа.
            districtTablePlaceholder.style.height = rect.height + "px";
            districtTablePlaceholder.style.display = "block";
            applyDistrictTableFixedBox(table, rect.left, rect.width);
            districtTableFixed = true;
        }
    } else {
        // Таблица зафиксирована — сверяемся с плейсхолдером: как только его
        // "родное" место в потоке документа снова опустится ниже порога
        // (то есть пользователь проскроллил обратно вверх), возвращаем
        // таблицу в обычное положение.
        const phRect = districtTablePlaceholder.getBoundingClientRect();
        if (phRect.top > STICKY_SCROLL_THRESHOLD) {
            resetDistrictTableInlineStyles(table);
            districtTablePlaceholder.style.display = "none";
            districtTableFixed = false;
        } else {
            // Остается зафиксированной — на случай ресайза окна подгоняем
            // ширину/отступ слева под текущий размер плейсхолдера.
            table.style.setProperty("left", phRect.left + "px", "important");
            table.style.setProperty("width", phRect.width + "px", "important");
        }
    }
}

function initDistrictTableSticky() {
    if (parentDoc.__districtStickyBound === true) return;
    parentDoc.__districtStickyBound = true;

    // capture: true — ключевой момент, см. пояснение в комментарии выше:
    // так обработчик ловит scroll от любого вложенного элемента, а не
    // только от window.
    parentDoc.addEventListener("scroll", syncDistrictTableSticky, true);
    window.parent.addEventListener("resize", syncDistrictTableSticky);
}

// =====================================================================
// КНОПКА "СБРОС ПРОГНОЗНЫХ ЗНАЧЕНИЙ" (страница 4, "СЦЕНАРИЙ №4")
// =====================================================================
// Раньше клик обрабатывался инлайн-атрибутом onclick="..." прямо в HTML,
// который передавался в st.markdown(..., unsafe_allow_html=True). Это
// оказалось ненадежно: Streamlit рендерит markdown-контент через
// react-markdown, и МНОГОСТРОЧНЫЙ атрибут onclick внутри "сырого" HTML-блока
// парсер иногда искажает (нормализует переносы строк/кавычки), из-за чего
// обработчик клика мог не навешиваться вообще.
// Вместо этого используем тот же надежный механизм делегирования событий,
// что уже применяется для стрелочек "да/нет" в npTable (см. initNpToggles
// выше по файлу): кнопка — это просто <button id="resetForecastBtn"> без
// каких-либо onclick-атрибутов, а слушатель клика навешивается один раз
// на весь parentDoc и сам находит нужную кнопку через closest(...).
function initResetForecastButton() {
    if (parentDoc.__resetForecastBound === true) return;
    parentDoc.__resetForecastBound = true;

    parentDoc.addEventListener("click", function (e) {
        const btn = e.target.closest("#resetForecastBtn");
        if (!btn) return;

        e.preventDefault();
        e.stopPropagation();

        // Плавно "гасим" экран оверлеем цвета фона, чтобы смягчить
        // визуальный переход перед настоящей перезагрузкой страницы.
        const overlay = parentDoc.getElementById("reset-forecast-overlay");
        if (overlay) overlay.classList.add("active");

        // window.parent — потому что этот скрипт выполняется внутри
        // iframe-компонента (components.html), а перезагрузить нужно
        // именно верхнюю (главную) страницу Streamlit-приложения.
        setTimeout(function () {
            window.parent.location.reload();
        }, 150);
    });
}

function makeSortable(tableId) {
    const table = parentDoc.getElementById(tableId);
    if (!table || !table.tBodies || !table.tBodies[0]) return;
    const tbody = table.tBodies[0];
    const headers = Array.from(table.tHead.rows[0].cells);
    headers.forEach((header, index) => {
        if (header.dataset.sortInitialized === "true") return;
        header.dataset.sortInitialized = "true";
        let asc = true;
        header.style.cursor = "pointer";
        header.onclick = () => {
            const rows = Array.from(tbody.rows);
            rows.sort((a, b) => {
                if (!a.cells[index] || !b.cells[index]) return 0;
                let v1 = a.cells[index].innerText.trim();
                let v2 = b.cells[index].innerText.trim();
                let n1 = parseFloat(v1.replace(",", "."));
                let n2 = parseFloat(v2.replace(",", "."));
                if (!isNaN(n1) && !isNaN(n2)) return asc ? n1 - n2 : n2 - n1;
                return asc ? v1.localeCompare(v2, 'ru') : v2.localeCompare(v1, 'ru');
            });
            // ИСПРАВЛЕНИЕ ГЛЮКА: сортировка сама по себе не должна вызывать
            // никакой вспышки и никакого пересчета значений — это просто
            // смена порядка строк. Но физическое перемещение строки в DOM
            // (tbody.appendChild(row) чуть ниже) браузер трактует как "узел
            // удалили и вставили заново", из-за чего CSS-анимация
            // @keyframes cellValueFlash ПЕРЕЗАПУСКАЕТСЯ на любой ячейке, у
            // которой класс .value-flash остался с предыдущего пересчета
            // (сам класс не снимается автоматически после того как анимация
            // доиграла до конца — см. flashCell). Поэтому перед перемещением
            // строк снимаем этот класс со всех ячеек таблицы, чтобы
            // reparenting ничего не "перезапускал".
            Array.from(table.querySelectorAll(".value-flash")).forEach(el => {
                el.classList.remove("value-flash");
            });
            rows.forEach(row => tbody.appendChild(row));
            headers.forEach(h => {
                const existingArrow = h.querySelector(".sort-arrow");
                if (existingArrow) existingArrow.remove();
                h.style.setProperty('background-color', '#f8f9fa', 'important');
            });
            if (asc) { header.style.setProperty('background-color', '#e8f8f5', 'important'); }
            else { header.style.setProperty('background-color', '#fdedec', 'important'); }
            const arrowSpan = parentDoc.createElement("span");
            arrowSpan.className = "sort-arrow";
            arrowSpan.innerHTML = asc ? "&#9650;" : "&#9660;";
            arrowSpan.style.color = asc ? "#27ae60" : "#e74c3c";
            header.appendChild(arrowSpan);
            rows.forEach(row => {
                row.classList.remove("pulse-highlight");
                void row.offsetWidth;
                row.classList.add("pulse-highlight");
                setTimeout(() => { row.classList.remove("pulse-highlight"); }, 600);
            });
            asc = !asc;
        };
    });
}

setInterval(() => {
    makeSortable("mainTable");
    makeSortable("npTable");
    lockSelectInput();
    initNpToggles();
    // triggeredByUserClick не передан (undefined -> false) — это фоновая
    // подстраховочная синхронизация по таймеру, а не реакция на клик,
    // поэтому вспышка здесь НЕ запускается (см. пояснение в
    // recalcDistrictToggleTotals — это и есть исправление глюка с
    // "неверное число на загрузке + вспышка -> верное число + вспышка").
    recalcDistrictToggleTotals();
    initResetForecastButton();   // навешивает делегированный обработчик клика (один раз)
    initDistrictTableSticky();   // навешивает scroll/resize-обработчики (один раз)
    syncDistrictTableSticky();   // подстраховка: синхронизирует состояние по таймеру
                                  // (например, если layout сдвинулся без события scroll —
                                  // из-за подгрузки шрифтов, данных и т.п.)
}, 500);

</script>
"""

# =============================================================================
# 9. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================
def _cell(df_ind, row, col):
    try:
        val = df_ind.iloc[row, col]
        if pd.isna(val):
            return ""
        if isinstance(val, float):
            if val == int(val):
                return str(int(val))
            return str(val)
        return str(val)
    except Exception:
        return ""

def build_page2_indicators_html(df_ind):
    if df_ind is None:
        return '<div style="padding:10px;text-align:center;color:#999;">Данные показателей не найдены</div>'
    
    tooltips_p2 = {
        0: "С учетом населенных пунктов с численностью населения от 100 человек и без учета городов.",
        2: "Головной офис, филиал, внутреннее структурное подразделение банка; мобильный банковский офис; удаленная точка с банковским работником.",
        3: "Стационарное отделение почтовой связи, передвижные отделения почтовой связи.",
        4: "Устройство самообслуживания банка для выдачи и приема денежных средств, оплаты услуг и совершения переводов без участия банковского сотрудника, с использованием и без использования банковских карт.",
        5: "Наличие возможности в торговой точке при оплате товара банковской картой дополнительно воспользоваться услугой по снятию наличных с банковской карты (доступно для ЮЛ и ИП с системой налогообложения ОСНО, УСН, ПСН)."
    }
    
    html = '<div class="indicators-row">'
    
    # Первая высокая карточка (колонка 0)
    tip_0 = tooltips_p2.get(0, "Подсказка")
    html += f'<div class="indicator-card indicator-card-tall">' \
            f'<div class="info-icon-wrapper">' \
            f'<span class="info-icon">i</span>' \
            f'<div class="custom-tooltip">{tip_0}</div>' \
            f'</div>' \
            f'<div class="card-line1">{_cell(df_ind,0,0)}</div>' \
            f'<div class="card-line2">{_cell(df_ind,1,0)}</div>' \
            f'<div class="card-line3">{_cell(df_ind,2,0)}</div>' \
            f'</div>'
    
    # Остальные карточки (колонки 2, 3, 4, 5)
    for col in [2, 3, 4, 5]:
        tip = tooltips_p2.get(col, f"Подсказка для показателя {col}")
        html += f'<div class="indicator-card">' \
                f'<div class="info-icon-wrapper">' \
                f'<span class="info-icon">i</span>' \
                f'<div class="custom-tooltip">{tip}</div>' \
                f'</div>' \
                f'<div class="card-line1">{_cell(df_ind,0,col)}</div>' \
                f'<div class="card-line2">{_cell(df_ind,1,col)}</div>' \
                f'<div class="card-line3">{_cell(df_ind,2,col)}</div>' \
                f'</div>'
                
    html += '</div>'
    return html

def build_page3_indicators_html(df_ind):
    if df_ind is None:
        return '<div style="padding:10px;text-align:center;color:#999;">Данные показателей не найдены</div>'
    
    tooltips_p3 = {
        1: "С учетом населенных пунктов с численностью населения от 100 человек и без учета городов.",
        6: "Рабочее место в общедоступном помещении с выходом в сеть Интернет, где жители сельской местности могут безопасно получить финансовые и государственные услуги, а также доступ к маркетплейсам, образовательным сервисам и сайтам по финансовой грамотности.",
        7: "Житель населенного пункта, который консультирует местных жителей по вопросам получения финансовых услуг и способствует организации альтернативных форматов банковского обслуживания."
    }
    
    html = '<div class="indicators-row">'
    
    # Первая карточка (колонка 1)
    tip_1 = tooltips_p3.get(1, "Подсказка")
    html += f'<div class="indicator-card indicator-card-tall">' \
            f'<div class="info-icon-wrapper">' \
            f'<span class="info-icon">i</span>' \
            f'<div class="custom-tooltip">{tip_1}</div>' \
            f'</div>' \
            f'<div class="card-line1">{_cell(df_ind,0,1)}</div>' \
            f'<div class="card-line2">{_cell(df_ind,1,1)}</div>' \
            f'<div class="card-line3">{_cell(df_ind,2,1)}</div>' \
            f'</div>'
    
    # Остальные карточки (колонки 6, 7)
    for col in [6, 7]:
        tip = tooltips_p3.get(col, f"Подсказка для показателя {col}")
        html += f'<div class="indicator-card">' \
                f'<div class="info-icon-wrapper">' \
                f'<span class="info-icon">i</span>' \
                f'<div class="custom-tooltip">{tip}</div>' \
                f'</div>' \
                f'<div class="card-line1">{_cell(df_ind,0,col)}</div>' \
                f'<div class="card-line2">{_cell(df_ind,1,col)}</div>' \
                f'<div class="card-line3">{_cell(df_ind,2,col)}</div>' \
                f'</div>'
                
    html += '</div>'
    return html

def render_footer():
    st.markdown(f"""
    <div class="footer">
        🏦 Информационный портал финансовой доступности | Разработано для органов государственной власти Новосибирской области | Посещений портала: <strong>{st.session_state.visit_count}</strong>
    </div>
    """, unsafe_allow_html=True)

# =============================================================================
# СЦЕНАРИЙ №1: ГЛАВНАЯ СТРАНИЦА
# =============================================================================
if st.session_state.page == 'home':
    st.markdown("""
    <div class="header-container">
        <div class="main-title">
            <h1>Информационная панель<br>доступности финансовых услуг в сельской местности<br>на территории Новосибирской области </h1>
        </div>
        <div class="sub-title">
            <p>30 муниципальных образований, 876 населенных пунктов (без учета городов и с численностью населения от 100 человек)</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    _, center_col, _ = st.columns([6, 1.2, 6])
    with center_col:
        st.markdown('<div class="date-picker-wrapper">', unsafe_allow_html=True)
#        dates_list = ["01.01.2025", "01.07.2025", "01.01.2026"]

        # 1. Получаем список дат для выбора (отсортированный)
#        dates_list = list(config.get("reporting_dates", {}).keys())

        st.selectbox(
            "Отчетная дата",
            dates_list,
            label_visibility="collapsed",
            key="selected_date",
            index=dates_list.index(current_date) if current_date in dates_list else 0,
            on_change=set_date_param
        )
        st.markdown('</div>', unsafe_allow_html=True)

    # Навигационные карточки
    st.markdown(f"""
    <div class="nav-cards-row">
        <a href="?page=page2&date={current_date}" class="nav-card" target="_self">
            <div class="nav-card-line1">Уровень финансовой доступности</div>
            <div class="nav-card-line2">Расчет в соответствии с Методикой Банка России</div>
        </a>
        <a href="?page=page3&date={current_date}" class="nav-card" target="_self">
            <div class="nav-card-line1">Уровень потребности в развитии дистанционного банковского обслуживания</div>
            <div class="nav-card-line2">Расчет в соответствии с подходами Сибирского ГУ Банка России</div>
        </a>
    </div>
    """, unsafe_allow_html=True)

#    st.markdown('<div class="custom-separator custom-separator1000"></div>', unsafe_allow_html=True)

    st.markdown("""
    <div class="home-info-text">
        <p><b>Информационная панель доступности финансовых услуг в сельской местности</b> – это интерактивный инструмент, демонстрирующий уровень доступности финансовых услуг и уровень потребности в развитии дистанционного банковского обслуживания на отдаленных, малонаселенных и труднодоступных территориях Новосибирской области.</p>
        <p>Данный инструмент предоставляет возможность региональным органам исполнительной власти и местного самоуправления:</p>
        <p>- получить информацию об инфраструктуре предоставления финансовых услуг для жителей сельской местности;</p>
        <p>- определять муниципальные образования / населенные пункты, требующие внимания;</p>
        <p>- планировать мероприятия, направленные на повышение доступности финансовых услуг (при поддержке Сибирского ГУ Банка России в части методологии);</p>
        <p>- формировать прогнозные значения показателей финансовой доступности за счет увеличения количества точек финансового доступа, финансовых помощников, торговых точек с сервисом выдачи наличных на кассе.</p>
    </div>
    """, unsafe_allow_html=True)


    st.markdown("<div style='margin-top: 40px;'></div>", unsafe_allow_html=True)

    # --- Кнопки нижнего ряда (чистый HTML, выравнивание по навигационным карточкам) ---
# --- Кнопки нижнего ряда (управляются через JS без перезагрузки) ---
    if b64_manual:
        st.markdown(f"""
        <div class="home-btns-row">
            <a class="home-btn" href="data:application/zip;base64,{b64_manual}" download="Руководство пользователя.zip" target="_self">
                📖 Руководство пользователя
            </a>
            <a class="home-btn" id="show-contacts-btn" href="javascript:void(0);">
                👥 Контакты представителей<br>Сибирского ГУ Банка России
            </a>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="home-btns-row">
            <div class="home-btn home-btn-disabled">
                📖 Руководство пользователя
            </div>
            <a class="home-btn" id="show-contacts-btn" href="javascript:void(0);">
                👥 Контакты представителей<br>Сибирского ГУ Банка России
            </a>
        </div>
        """, unsafe_allow_html=True)

    # --- Таблица контактов ---
# --- Таблица контактов (скрыта по умолчанию) ---
    st.markdown(f"""
    <div class="contacts-table-container" id="contacts-table-container" style="display: none;">
        <div class="contacts-table-header">
            <span class="contacts-header">Контакты представителей Сибирского ГУ Банка России</span>
            <a href="javascript:void(0)" class="contacts-table-close" id="close-contacts-btn" title="Закрыть">&times;</a>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Должность</th>
                    <th style="width: 160px;">ФИО</th>
                    <th style="width: 120px;">Телефон</th>
                    <th style="width: 180px;">Электронная почта</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>Начальник Управления платежных систем и расчетов</td>
                    <td>Барбанакова<br>Надежда Алексеевна</td>
                    <td>(383) 217-63-56</td>
                    <td><a href="mailto:BarabanakovaNA@cbr.ru">BarabanakovaNA@cbr.ru</a></td>
                </tr>
                <tr>
                    <td>Заместитель начальника Управления - начальник отдела развития национальной платежной системы</td>
                    <td>Лысенко<br>Роман Юрьевич</td>
                    <td>(383) 217-63-49</td>
                    <td><a href="mailto:LysenkoRY@cbr.ru">LysenkoRY@cbr.ru</a></td>
                </tr>
                <tr>
                    <td>Руководитель направления</td>
                    <td>Ермошина<br>Елена Сергеевна</td>
                    <td>(383) 217-67-59</td>
                    <td><a href="mailto:ErmoshinaES@cbr.ru">ErmoshinaES@cbr.ru</a></td>
                </tr>
            </tbody>
        </table>
    </div>
    """, unsafe_allow_html=True)

    # JS-обработчик для мгновенного открытия и закрытия таблицы без перезагрузки
    components.html("""
    <script>
    const parentDoc = window.parent.document;
    
    const showBtn = parentDoc.getElementById('show-contacts-btn');
    const closeBtn = parentDoc.getElementById('close-contacts-btn');
    const container = parentDoc.getElementById('contacts-table-container');

    if (showBtn && container) {
        showBtn.onclick = function(e) {
            e.preventDefault();
            container.style.display = 'block';
            container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        };
    }

    if (closeBtn && container) {
        closeBtn.onclick = function(e) {
            e.preventDefault();
            container.style.display = 'none';
        };
    }
    </script>
    """, height=0)

    render_footer()

# =============================================================================
# СЦЕНАРИЙ №2: УРОВЕНЬ ФИНАНСОВОЙ ДОСТУПНОСТИ
# =============================================================================
elif st.session_state.page == 'page2':
    st.markdown('<div class="back-btn-container">', unsafe_allow_html=True)
    if st.button("⬅️ Возврат на главную страницу"):
        go_home()
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # Индикаторные карточки
    st.markdown(build_page2_indicators_html(df_indicators), unsafe_allow_html=True)

    # Три колонки: 20% — 10% — 70%
    left_col, mid_col, right_col = st.columns([2, 1, 7])

    with left_col:
        st.markdown('<div class="left-panel-section">', unsafe_allow_html=True)

        # Кнопка «Список муниципальных образований… / Выгрузить в Excel»
        if b64_excel_f:
            safe_date = current_date.replace(".", "-")
            st.markdown(f"""
            <a class="left-panel-btn" href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64_excel_f}" download="NSO_f_regions_{current_date}.xlsx">
                <div class="left-panel-btn-line1">Список муниципальных образований Новосибирской области</div>
                <div class="left-panel-btn-line2">Выгрузить в Excel</div>
            </a>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class="left-panel-btn" style="opacity:0.5; cursor:default; pointer-events:none;">
                <div class="left-panel-btn-line1">Список муниципальных образований Новосибирской области</div>
                <div class="left-panel-btn-line2">Выгрузить в Excel (файл не найден)</div>
            </div>
            """, unsafe_allow_html=True)

        # Кнопка «Интерактивная карта СФО»
        if b64_sfo_map:
            st.markdown(f"""
            <a class="left-panel-btn" href="Интерактивная карта СФО.xlsm" download="Интерактивная карта СФО.xlsm">
                <div class="left-panel-btn-line1">Интерактивная карта Финансовой доступности <br> в разрезе субъектов <br> Сибирского Федерального Округа</div>
            </a>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class="left-panel-btn" style="opacity:0.5; cursor:default; pointer-events:none;">
                <div class="left-panel-btn-line1">Интерактивная карта Финансовой доступности <br> в разрезе субъектов <br> Сибирского Федерального Округа (файл не найден)</div>
            </div>
            """, unsafe_allow_html=True)

        # Таблица уровней
        st.markdown("""
        <table id="weights" class="weights-table" style="width: 100% !important;">
            <thead>
                <tr>
                    <th>Уровень финансовой доступности</th>
                    <th>Значение, %</th>
                </tr>
            </thead>
            <tbody>
                <tr><td>Хороший</td><td style="background-color: #88A945;">86 – 100</td></tr>
                <tr><td>Выше среднего</td><td style="background-color: #D8E4BC;">66 – 85</td></tr>
                <tr><td>Средний</td><td style="background-color: #FFFFCC;">46 – 65</td></tr>
                <tr><td>Ниже среднего</td><td style="background-color: #FCD5B4;">31 – 45</td></tr>
                <tr><td>Недостаточный</td><td style="background-color: #E6B8B7;">0 – 30</td></tr>
            </tbody>
        </table>
        """, unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

    with mid_col:
        st.empty()

    with right_col:
        st.markdown('<div class="right-panel-title">Тепловая карта уровня финансовой доступности на территории Новосибирской области</div>', unsafe_allow_html=True)

        if heatmap_svg:
            st.markdown(f'<div class="heatmap-wrapper">{heatmap_svg}</div>', unsafe_allow_html=True)
        else:
            st.warning(f"Файл тепловой карты {HEATMAP_SVG_FILE} не найден.")

        st.markdown("""
        <div class="heatmap-legend">
            <div class="heatmap-legend-line"></div>
            <span class="heatmap-legend-text">Границы районов с концентрацией более 30% населенных пунктов с уровнем финансовой доступности 65% и ниже</span>
        </div>
        """, unsafe_allow_html=True)

    render_footer()

# =============================================================================
# СЦЕНАРИЙ №3: УРОВЕНЬ ПОТРЕБНОСТИ В ДБО
# =============================================================================
elif st.session_state.page == 'page3':
    st.markdown('<div class="back-btn-container">', unsafe_allow_html=True)
    if st.button("⬅️ Возврат на главную страницу"):
        go_home()
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # Индикаторные карточки
    st.markdown(build_page3_indicators_html(df_indicators), unsafe_allow_html=True)

    # Три колонки: 20% — 10% — 70%
    left_col, mid_col, right_col = st.columns([2, 1, 7])

    with left_col:
        st.markdown('<div class="left-panel-section">', unsafe_allow_html=True)

        # Кнопка «Список муниципальных образований… / Выгрузить в Excel»
        if b64_excel_p:
            st.markdown(f"""
            <a class="left-panel-btn" href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64_excel_p}" download="NSO_p_regions_{current_date}.xlsx">
                <div class="left-panel-btn-line1">Список муниципальных образований Новосибирской области</div>
                <div class="left-panel-btn-line2">Выгрузить в Excel</div>
            </a>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class="left-panel-btn" style="opacity:0.5; cursor:default; pointer-events:none;">
                <div class="left-panel-btn-line1">Список муниципальных образований Новосибирской области</div>
                <div class="left-panel-btn-line2">Выгрузить в Excel (файл не найден)</div>
            </div>
            """, unsafe_allow_html=True)

        # Таблица уровней потребности
        st.markdown("""
        <table id="Needs" class="Needs-table" style="width: 100% !important;">
            <thead>
                <tr>
                    <th>Уровень потребности в развитии дистанционного банковского обслуживания</th>
                    <th  style="width: 100px">Значение, %</th>
                </tr>
            </thead>
            <tbody>
                <tr><td>Низкий</td><td style="background-color: #88A945;">0 – 10</td></tr>
                <tr><td>Выше низкого</td><td style="background-color: #D8E4BC;">11 – 15</td></tr>
                <tr><td>Средний</td><td style="background-color: #FFFFCC;">16 – 20</td></tr>
                <tr><td>Выше среднего</td><td style="background-color: #FCD5B4;">21 – 30</td></tr>
                <tr><td>Высокий</td><td style="background-color: #E6B8B7;">31 – 100</td></tr>
            </tbody>
        </table>
        """, unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

    with mid_col:
        st.empty()

    with right_col:
        st.markdown('<div class="right-panel-title">Интерактивная карта распределения уровня потребности в развитии<br>дистанционного банковского обслуживания на территории Новосибирской области</div>', unsafe_allow_html=True)

        if interactive_svg:
            st.markdown(f'<div class="svg-wrapper-50"><div class="svg-wrapper">{interactive_svg}</div></div>', unsafe_allow_html=True)
        else:
            st.warning(f"Файл карты {SVG_FILE} не найден.")

    render_footer()

# =============================================================================
# СЦЕНАРИЙ №4: СТРАНИЦА РАЙОНА
# =============================================================================
elif st.session_state.page == 'district':
    region_id = st.session_state.selected_region

    from_page = query_params.get("from_page", "home")
    if isinstance(from_page, list):
        from_page = from_page[0]

    if from_page in ('page2', 'page3'):
        back_href = f"?page={from_page}&date={current_date}"
    else:
        back_href = f"?date={current_date}"

    st.markdown(f'''
    <div class="back-btn-container">
        <a href="{back_href}" target="_self" class="back-link">⬅️ Возврат на предыдущую страницу</a>
    </div>
    ''', unsafe_allow_html=True)

    if not display_df.empty:
        region_row = display_df[display_df['ID'].astype(str).str.strip() == str(region_id).strip()]

        if not region_row.empty:
            region_name = region_row['Район'].values[0]

            # --- Сначала считаем данные по населенным пунктам района (нужны для счетчика "Количество населенных пунктов") ---
            cols_to_show = [col for col in region_row.columns if col != 'ID']
            np_display_cols = []
            for col in cols_to_show:
                if col == "Район":
                    np_display_cols.append("Населенный пункт")
                else:
                    np_display_cols.append(col)

            df_np_region = pd.DataFrame()
            if df_np_all is None:
                st.error(f"❌ Файл {NP_FILE} не найден.")
            else:
                mask = df_np_all["Район"].astype(str).str.strip() == str(region_name).strip()
                available_cols = [c for c in np_display_cols if c in df_np_all.columns]
                df_np_region = df_np_all[mask][available_cols].copy()
                if "Населенный пункт" in df_np_region.columns:
                    df_np_region = df_np_region.sort_values("Населенный пункт").reset_index(drop=True)

            b64_np_excel = convert_df_to_excel_b64(df_np_region, sheet_name='Населенные пункты') if not df_np_region.empty else ""

            # --- Агрегаты по населенным пунктам ВНЕ текущего района (для
            # пересчета строки "Новосибирская область" в districtTable) ---
            # Считаются один раз при загрузке страницы (с кэшированием через
            # st.cache_data внутри compute_other_districts_affordability_aggregates)
            # и передаются в браузер JS-скриптом ниже. Подробное обоснование
            # этого подхода — см. комментарии к recalcOblastRowAffordabilityAggregates
            # в sorting_script (блок "8. JS СКРИПТ ДЛЯ СОРТИРОВКИ ТАБЛИЦ").
            oblast_other_aggregates = compute_other_districts_affordability_aggregates(NP_FILE, region_name)
            components.html(
                f"<script>window.parent.__oblastOtherAggregates = {json.dumps(oblast_other_aggregates)};</script>",
                height=0,
            )

            # -----------------------------------------------------------------
            # Макет строки под кнопкой "Возврат на предыдущую страницу":
            # три колонки [3, 3, 3]:
            #   1) кнопка "Сброс прогнозных значений"
            #   2) заголовок района / счетчик НП / подпись / дата
            #   3) заголовок "Величина поправочного коэффициента..." и таблица weights_np
            # -----------------------------------------------------------------
            col_reset, col_header, col_weights = st.columns([3, 3, 3])

            with col_reset:
                # 1. Стили для кнопки: принудительная ширина 322px и отступ
                #    (внешний вид сохранен таким же, как был у st.button, но теперь
                #    это обычная HTML-кнопка — см. пункт 3 ниже, почему)
                st.markdown('''
                    <style>
                        /* Кнопка "Сброс прогнозных значений": визуально повторяет
                           стандартную кнопку Streamlit (белый фон, серая рамка,
                           скругление), но является обычным HTML-элементом */
                        .reset-forecast-btn {
                            display: inline-flex;
                            align-items: center;
                            justify-content: center;
                            width: 322px !important;
                            height: 90px !important;
                            max-width: 322px !important;
                            padding: 0.5rem 0.75rem;
                            font-family: var(--font-ui);
                            font-size: 16px;
                            font-weight: 550;
                            line-height: 1.6;
                            color: #31333F;
                            background-color: #ffffff;
                            border: 1px solid rgba(49, 51, 63, 0.2);
                            border-radius: 8px;
                            cursor: pointer;
                            transition: border-color 0.15s ease, color 0.15s ease;
                        }
                        .reset-forecast-btn:hover {
                            border-color: #ff4b4b;
                            color: #ff4b4b;
                        }
                        .reset-forecast-btn:active {
                            border-color: #ff4b4b;
                            color: #ffffff;
                            background-color: #ff4b4b;
                        }

                        /* Оверлей, которым мы на мгновение "накрываем" страницу перед
                           перезагрузкой (location.reload), чтобы сгладить моргание:
                           вместо резкого бело-серого мигания браузера пользователь
                           видит плавное короткое затемнение/осветление в цвет фона */
                        #reset-forecast-overlay {
                            position: fixed;
                            inset: 0;
                            background-color: #ffffff;
                            opacity: 0;
                            pointer-events: none;
                            z-index: 999999;
                            transition: opacity 0.15s ease-in;
                        }
                        #reset-forecast-overlay.active {
                            opacity: 1;
                            pointer-events: all;
                        }
                    </style>
                ''', unsafe_allow_html=True)

                # 2. Простое и надежное смещение кнопки вниз с помощью отступа
                st.markdown('<div style="margin-top: 280px;"></div>', unsafe_allow_html=True)

                # 3. Кнопка "Сброс прогнозных значений".
                #    ВАЖНО: раньше здесь был st.button(...) с вызовом st.rerun() —
                #    но это лишь перезапускало python-скрипт Streamlit, а сами
                #    расчеты (переключатели "да/нет" в npTable и суммы в
                #    districtTable) хранятся не на сервере, а прямо в DOM браузера
                #    (см. JS-функции recalcDistrictToggleTotals / initNpToggles
                #    ниже по файлу). Поэтому st.rerun() их фактически НЕ сбрасывал.
                #    Теперь это обычная HTML-кнопка (без атрибута onclick —
                #    клик обрабатывается делегированным JS-слушателем
                #    initResetForecastButton() внутри components.html-скрипта,
                #    см. подробное объяснение там же, почему инлайн-onclick
                #    оказался ненадежным). По клику она подсвечивает
                #    полупрозрачный оверлей и через 150 мс запускает
                #    window.parent.location.reload() — то есть выполняет ПОЛНУЮ
                #    перезагрузку текущей страницы браузером, как кнопка
                #    "Обновить эту страницу" в Chrome. При такой перезагрузке
                #    гарантированно сбрасывается вообще всё: и JS-расчеты в
                #    DOM, и любые введенные пользователем значения, а сама
                #    страница отрисовывается заново "с нуля". Небольшая пауза
                #    перед reload() нужна только для того, чтобы браузер успел
                #    доиграть анимацию оверлея (полностью убрать моргание при
                #    настоящей перезагрузке страницы физически невозможно —
                #    это ограничение самого браузера, но так оно сглаживается).
                #    Строка ниже намеренно однострочная (без переносов
                #    внутри HTML) — react-markdown, через который Streamlit
                #    рендерит unsafe_allow_html-контент, может искажать
                #    многострочные HTML-блоки/атрибуты.
                st.markdown('<div id="reset-forecast-overlay"></div><button type="button" id="resetForecastBtn" class="reset-forecast-btn">🔄 Сброс прогнозных значений</button>', unsafe_allow_html=True)

            with col_header:
                st.markdown(f'<h2 style="font-family: var(--font-ui); text-align: center; font-size: 28px !important; font-weight: 700; color: #1a252c; margin-top: -20px; margin-bottom: 5px; letter-spacing: -0.01em;">{region_name}</h2>', unsafe_allow_html=True)
                st.markdown(f'<div class="district-section-title">Количество населенных пунктов: {len(df_np_region)}</div>', unsafe_allow_html=True)
                st.markdown('<div style="font-family: var(--font-ui); font-size: 16px; font-weight: 600; color: #1a252c; margin-top: 10px; margin-bottom: 8px; text-align: center;">(без городов и с численностью населения от 100 чел.)</div>', unsafe_allow_html=True)
                st.markdown(f'<h5 style="font-family: var(--font-ui); text-align: center; font-size: 16px !important; font-weight: 600; color: #1a252c; margin-top: 10px; margin-bottom: 10px; letter-spacing: 0.05em;">на {current_date}</h5>', unsafe_allow_html=True)

            with col_weights:
                # --- ТАБЛИЦА «УДЕЛЬНЫЕ ВЕСА» (перенесена сюда, в правую колонку) ---
                st.markdown("""
                <div style="display: flex; flex-direction: column; align-items: center; padding-left: 70px;">
                    <div style="font-family: var(--font-ui); font-size: 16px; font-weight: 600; line-height: 1.5; text-align: center; margin-bottom: 10px; color: #1a252c;">
                        Величина поправочного коэффициента к уровню потребности <br>в развитии дистанционного банковского обслуживания в зависимости <br>от уровня финансовой доступности населенного пункта
                    </div>
                    <div style="max-width: 900px; width: 100%;">
                        <table id="weights_np" class="weights-table weights-correct" style="width: 100% !important;">
                            <thead>
                                <tr>
                                    <th style="width: 132px;">Уровень финансовой доступности</th>
                                    <th style="width: 100px;">Значение, %</th>
                                    <th style="width: 132px;">Наличие Точки финансового доступа</th>
                                    <th style="width: 132px;">Присутствие Финансового помощника, %</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr><td>Хороший</td><td>86 – 100</td><td>0</td><td>2</td></tr>
                                <tr><td>Выше среднего</td><td>66 – 85</td><td>1</td><td>3</td></tr>
                                <tr><td>Средний</td><td>46 – 65</td><td>2</td><td>4</td></tr>
                                <tr><td>Ниже среднего</td><td>31 – 45</td><td>3</td><td>5</td></tr>
                                <tr><td>Недостаточный</td><td>0 – 30</td><td>4</td><td>6</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
                """, unsafe_allow_html=True)

            st.markdown('<div class="custom-separator"></div>', unsafe_allow_html=True)

            district_row_data = region_row[cols_to_show].copy()
            dist_headers = list(cols_to_show)
            dist_header_html = "".join(
                f'<th data-colname="{html.escape(str(c))}">{c}</th>' for c in dist_headers
            )

            # --- ФОРМИРОВАНИЕ СТРОКИ НСО ---
            nso_row_html = ""
            if df_nso_summary is not None and not df_nso_summary.empty:
                nso_row = df_nso_summary.iloc[0]
                nso_cells = ""
                for col in cols_to_show:
                    if col == "Район":
                        nso_cells += f'<td style="font-weight: 700 !important;">Новосибирская область</td>'
                        continue
                    val = nso_row.get(col, "")
                    if str(col).startswith(("Уровень")) and pd.notna(val):
                        try:
                            num_val = float(str(val).replace('%', '').replace(',', '.').strip())
                            if num_val <= 1.0:
                                num_val *= 100
                            css_class = get_need_level_class(col, num_val)
                            nso_cells += f'<td class="{css_class}">{num_val:.1f}%</td>'
                        except Exception:
                            nso_cells += f'<td>{val}</td>'

                    # ДОБАВЛЕННЫЙ БЛОК:
                    elif str(col).startswith(("Изменение уровня")) and pd.notna(val):
                        try:
                            num_val = float(str(val).replace(',', '.').strip())

                            # Определяем цвет, стрелку и форматирование
                            if num_val > 0:
                                css_class = "change-pos-custom"
                                arrow = "&#11014;"
                                formatted_val = f"+{num_val:.1f}"
                            elif num_val < 0:
                                css_class = "change-neg-custom"
                                arrow = "&#11015;"
                                formatted_val = f"{num_val:.1f}"
                            else:
                                css_class = ""
                                arrow = ""
                                formatted_val = "0.0"

                            # Теперь используем класс, который перекроет глобальный цвет
                            nso_cells += f'<td class="{css_class}">{arrow} {formatted_val}</td>'

                        except (ValueError, TypeError):
                            nso_cells += f'<td>{val}</td>'

                    else:
                        nso_cells += f'<td>{val if pd.notna(val) else ""}</td>'
                nso_row_html = f'<tr style="background-color: #e8f4f8">{nso_cells}</tr>'

            # --- ФОРМИРОВАНИЕ СТРОКИ РАЙОНА ---
            dist_cells = ""
            for col in cols_to_show:
                val = district_row_data[col].values[0]
                if str(col).startswith(("Уровень")) and pd.notna(val):
                    try:
                        num_val = float(str(val).replace('%', '').replace(',', '.').strip())
                        if num_val <= 1.0:
                            num_val *= 100
                        css_class = get_need_level_class(col, num_val)
                        dist_cells += f'<td class="{css_class}">{num_val:.1f}%</td>'
                    except Exception:
                        dist_cells += f'<td>{val}</td>'

                # ДОБАВЛЕННЫЙ БЛОК:
                elif str(col).startswith(("Изменение уровня")) and pd.notna(val):
                    try:
                        num_val = float(str(val).replace(',', '.').strip())

                        # Определяем цвет, стрелку и форматирование
                        if num_val > 0:
                            css_class = "change-pos-custom"
                            arrow = "&#11014;"
                            formatted_val = f"+{num_val:.1f}"
                        elif num_val < 0:
                            css_class = "change-neg-custom"
                            arrow = "&#11015;"
                            formatted_val = f"{num_val:.1f}"
                        else:
                            css_class = ""
                            arrow = ""
                            formatted_val = "0.0"

                        # Теперь используем класс, который перекроет глобальный цвет
                        dist_cells += f'<td class="{css_class}">{arrow} {formatted_val}</td>'

                    except (ValueError, TypeError):
                        dist_cells += f'<td>{val}</td>'

                else:
                    dist_cells += f'<td>{val if pd.notna(val) else ""}</td>'

            # Таблица districtTable рендерится как обычно, без специальных
            # оберток. Причина: и sticky на th/tr/td по отдельности (попытка №1,
            # строки схлопывались друг на друга), и sticky на едином враппере
            # вокруг таблицы (попытка №2, где-то по цепочке предков Streamlit
            # обрезает/ограничивает sticky-контекст) не дали нужного результата.
            # Поэтому фиксацию таблицы при скролле теперь полностью делает JS
            # (position: fixed) — см. функцию syncDistrictTableSticky в блоке
            # "8. JS СКРИПТ ДЛЯ СОРТИРОВКИ ТАБЛИЦ". Она ловит скролл через
            # capture-фазу (см. подробный комментарий в JS), поэтому работает
            # независимо от того, какой именно элемент физически прокручивается
            # внутри Streamlit-разметки, — обертка вокруг таблицы для этого
            # не нужна.
            district_table_html = f"""
            <table id="districtTable">
                <thead><tr>{dist_header_html}</tr></thead>
                <tbody>
                    {nso_row_html}
                    <tr>{dist_cells}</tr>
                </tbody>
            </table>
            """
            st.markdown(district_table_html, unsafe_allow_html=True)


            st.markdown('<div class="district-section-title">Населенные пункты</div>', unsafe_allow_html=True)
            st.markdown('<div class="sort-caption">(работает сортировка по нажатию на заголовки)</div>', unsafe_allow_html=True)

            if not df_np_region.empty:
                np_headers_html = "".join(
                    f'<th data-colname="{html.escape(str(c))}">{c}</th>' for c in available_cols
                )
                np_rows_html = ""
                for _, row in df_np_region.iterrows():
                    cells = ""
                    for col in available_cols:
                        val = row[col]
                        if col in TOGGLE_YES_NO_COLUMNS:
                            # Переключатель "да/нет" со стрелочками вверх-вниз:
                            # 0 (или отсутствие значения) -> "нет", любое положительное число -> "да"
                            try:
                                num_val = float(str(val).replace(',', '.').strip())
                            except (ValueError, TypeError):
                                num_val = 0
                            state = "yes" if num_val > 0 else "no"
                            state_label = "да" if state == "yes" else "нет"
                            cells += (
                                f'<td class="np-toggle-cell" data-state="{state}">'
                                f'<span class="toggle-widget">'
                                f'<button type="button" class="toggle-arrow toggle-arrow-up" title="Да">&#9650;</button>'
                                f'<span class="toggle-value">{state_label}</span>'
                                f'<button type="button" class="toggle-arrow toggle-arrow-down" title="Нет">&#9660;</button>'
                                f'</span>'
                                f'</td>'
                            )
                        elif pd.notna(val) and str(col).startswith(("Уровень")):
                            try:
                                num_val = float(str(val).replace('%', '').replace(',', '.').strip())
                                if num_val <= 1.0:
                                    num_val = num_val * 100
                                css_class = get_need_level_class(col, num_val)
                                cells += f'<td class="{css_class}">{num_val:.1f}%</td>'
                            except (ValueError, TypeError):
                                cells += f'<td>{val}</td>'

                        # ДОБАВЛЕННЫЙ БЛОК:
                        elif pd.notna(val) and str(col).startswith(("Изменение уровня")):
                            try:
                                num_val = float(str(val).replace(',', '.').strip())

                                # Определяем цвет, стрелку и форматирование
                                if num_val > 0:
                                    css_class = "change-pos-custom"
                                    arrow = "&#11014;"
                                    formatted_val = f"+{num_val:.1f}"
                                elif num_val < 0:
                                    css_class = "change-neg-custom"
                                    arrow = "&#11015;"
                                    formatted_val = f"{num_val:.1f}"
                                else:
                                    css_class = ""
                                    arrow = ""
                                    formatted_val = "0.0"

                                # Теперь используем класс, который перекроет глобальный цвет
                                cells += f'<td class="{css_class}">{arrow} {formatted_val}</td>'

                            except (ValueError, TypeError):
                                cells += f'<td>{val}</td>'

                        else:
                            cells += f'<td>{val if pd.notna(val) else ""}</td>'
                    np_rows_html += f'<tr>{cells}</tr>\n'

                np_table_html = f"""
                <table id="npTable">
                    <thead><tr>{np_headers_html}</tr></thead>
                    <tbody>{np_rows_html}</tbody>
                </table>
                """
                st.markdown(np_table_html, unsafe_allow_html=True)

            st.markdown("<div style='margin-top: 30px;'></div>", unsafe_allow_html=True)

            # Кнопки выгрузки на странице района
            btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 1])

            with btn_col1:
                if b64_tfd:
                    st.markdown(
                        f'''<div class="centered-portal-btn">
                                <a class="portal-btn w400" href="data:application/zip;base64,{b64_tfd}" download="Как открыть ТФД.zip">📖 Как открыть Точку финансового доступа</a>
                            </div>''', 
                        unsafe_allow_html=True
                    )

            with btn_col2:
                if b64_fp:
                    st.markdown(
                        f'''<div class="centered-portal-btn">
                                <a class="portal-btn w400" href="data:application/zip;base64,{b64_fp}" download="Как назначить ФП.zip">📖 Как назначить Финансового помощника</a>
                            </div>''', 
                        unsafe_allow_html=True
                    )

            with btn_col3:
                if b64_tcash:
                    st.markdown(
                        f'''<div class="centered-portal-btn">
                                <a class="portal-btn w400" href="data:application/zip;base64,{b64_tcash}" download="Как подключить точку кэшаут.zip">📖 Как подключить точку кэшаут</a>
                            </div>''', 
                        unsafe_allow_html=True
                    )

        render_footer()

# =============================================================================
# ИНЪЕКЦИЯ JS-СКРИПТА СОРТИРОВКИ
# =============================================================================
components.html(sorting_script, height=0)