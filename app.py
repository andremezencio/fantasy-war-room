import streamlit as st
import pandas as pd
import requests
import unicodedata
import re
from streamlit_gsheets import GSheetsConnection

# Configuração da Página - Layout Wide para melhor visualização das tabelas
st.set_page_config(page_title="War Room 2026", layout="wide", page_icon="🏈")

# --- ESTILO CSS PARA MELHORAR O VISUAL ---
st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] {
        background-color: #1e2130;
        border-radius: 4px 4px 0px 0px;
        padding: 10px 20px;
        color: white;
    }
    .stTabs [aria-selected="true"] { background-color: #4CAF50 !important; }
    </style>
    """, unsafe_allow_html=True)

# --- FUNÇÕES DE APOIO ---
def clean_num(val):
    if pd.isna(val) or val == 0: return 0.0
    if isinstance(val, str):
        return float(val.replace('.', '').replace(',', '.'))
    return float(val)

def normalize_name(name):
    if not isinstance(name, str): return ""
    name = "".join(c for c in unicodedata.normalize('NFD', name) if unicodedata.category(c) != 'Mn')
    name = re.sub(r'[^a-zA-Z]', '', name.lower())
    for suffix in ['jr', 'iii', 'ii', 'sr', 'iv']:
        if name.endswith(suffix): name = name[:-len(suffix)]
    return name.strip()

@st.cache_data(ttl=3600)
def get_sleeper_players():
    res = requests.get("https://api.sleeper.app/v1/players/nfl")
    players = res.json()
    mapping = {f"{v['first_name']} {v['last_name']}": k for k, v in players.items() if v.get('active')}
    mapping["Lamar Jackson"] = "4881" # Correção manual do QB
    return mapping

def calculate_war_room_score(df):
    def score_row(row):
        adp_real = row.get('ADP', 0)
        if adp_real <= 0: adp_real = 210.0
        v_media = row.get('Media_4_Anos', 0) * 0.08
        v_adp = (210 - adp_real) * 0.9
        v_proj = row.get('Proj', 0) * 0.02
        score_base = v_media + v_adp + v_proj
        pos = str(row.get('FantPos', '')).upper().strip()
        perf_factor = min(1.0, row.get('Media_4_Anos', 0) / 120)
        if pos in ['RB', 'WR']: mult = 1.3 + (0.5 * perf_factor)
        elif pos in ['QB', 'TE']: mult = 1.2 + (0.25 * perf_factor)
        elif pos in ['DEF', 'K']: mult = 0.7 + (0.2 * perf_factor)
        else: mult = 1.0
        return score_base * mult
    df['Score_Final'] = df.apply(score_row, axis=1)
    return df

# --- BARRA LATERAL (CONFIGURAÇÕES) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/5351/5351486.png", width=100)
    st.title("War Room Config")
    draft_id = st.text_input("Sleeper Draft ID", value="1314740945048043520")
    
    if st.button("🔄 Forçar Atualização"):
        st.cache_data.clear()
        st.rerun()
    
    st.divider()
    st.info("O algoritmo prioriza ADP (90%) com bônus de performance histórica.")

# --- PROCESSAMENTO ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_raw = conn.read(spreadsheet=st.secrets["spreadsheet_url"])
    for col in ['Proj', 'ADP', 'Media_4_Anos']:
        df_raw[col] = df_raw[col].apply(clean_num)
    
    name_to_id = get_sleeper_players()
    normalized_sleeper_map = {normalize_name(name): pid for name, pid in name_to_id.items()}
    
    picks_res = requests.get(f"https://api.sleeper.app/v1/draft/{draft_id}/picks")
    picks_data = picks_res.json()
    picked_ids_str = [str(p['player_id']) for p in picks_data]
    picked_names_set = set([normalize_name(p.get('metadata', {}).get('full_name', '')) for p in picks_data])
    
    df_scored = calculate_war_room_score(df_raw)
    df_scored['norm_name'] = df_scored['Player'].apply(normalize_name)
    df_scored['sleeper_id'] = df_scored['norm_name'].map(normalized_sleeper_map)
    
    def is_available(row):
        sid = str(row['sleeper_id']) if pd.notna(row['sleeper_id']) else ""
        if sid in picked_ids_str: return False
        if row['norm_name'] in picked_names_set: return False
        return True

    available = df_scored[df_scored.apply(is_available, axis=1)].copy()
    available = available.sort_values(by='Score_Final', ascending=False)

    # --- ÁREA PRINCIPAL (UI) ---
    col1, col2, col3 = st.columns([1, 1, 2])
    col1.metric("Pick Atual", len(picks_data) + 1)
    col2.metric("Disponíveis", len(available))
    if picks_data:
        last = picks_data[-1]
        nome_l = last.get('metadata', {}).get('full_name', f"ID: {last['player_id']}")
        col3.metric("Última Pick", nome_l)

    st.divider()

    # --- ABAS DE POSIÇÃO ---
    tab_geral, tab_qb, tab_rb, tab_wr, tab_te, tab_flex, tab_def_k = st.tabs([
        "💎 Geral", "🏈 QB", "🏃 RB", "👐 WR", "🧤 TE", "🔄 FLEX", "🛡️ DEF/K"
    ])

    def show_table(data):
        st.dataframe(
            data[['Player', 'FantPos', 'Media_4_Anos', 'ADP', 'Proj', 'Score_Final']].head(30),
            column_config={
                "Score_Final": st.column_config.ProgressColumn("Value Score", format="%.1f", min_value=0, max_value=250),
                "Media_4_Anos": "Média Hist.",
                "Proj": "Proj. 2026",
                "ADP": "ADP"
            },
            hide_index=True, use_container_width=True
        )

    with tab_geral:
        st.subheader("Top 30 Best Available")
        show_table(available)

    with tab_qb:
        st.subheader("Quarterbacks")
        show_table(available[available['FantPos'] == 'QB'])

    with tab_rb:
        st.subheader("Running Backs")
        show_table(available[available['FantPos'] == 'RB'])

    with tab_wr:
        st.subheader("Wide Receivers")
        show_table(available[available['FantPos'] == 'WR'])

    with tab_te:
        st.subheader("Tight Ends")
        show_table(available[available['FantPos'] == 'TE'])
    
    with tab_flex:
        st.subheader("FLEX (RB/WR/TE)")
        show_table(available[available['FantPos'].isin(['RB', 'WR', 'TE'])])

    with tab_def_k:
        st.subheader("Defesas e Kickers")
        show_table(available[available['FantPos'].isin(['DEF', 'K'])])

    # Diagnóstico escondido no final
    with st.expander("🛠️ Ferramentas de Diagnóstico"):
        st.write("Draft ID Ativo:", draft_id)
        if st.checkbox("Verificar IDs mapeados"):
            st.write(available[['Player', 'sleeper_id']].head(10))

except Exception as e:
    st.error(f"⚠️ Erro ao carregar dados: {e}")
    st.info("Verifique se o Draft ID está correto ou se a planilha está acessível.")
