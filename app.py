import streamlit as st
import pandas as pd
import requests
from streamlit_gsheets import GSheetsConnection

# Configuração da Página
st.set_page_config(page_title="Fantasy War Room 2026", layout="wide", page_icon="🏈")

# --- ESTILIZAÇÃO CUSTOMIZADA ---
st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    .stMetric { background-color: #1e2130; padding: 15px; border-radius: 10px; border: 1px solid #3e4255; }
    </style>
    """, unsafe_allow_html=True)

# --- FUNÇÕES DE APOIO ---
def clean_num(val):
    if pd.isna(val) or val == 0: return 0.0
    if isinstance(val, str):
        return float(val.replace('.', '').replace(',', '.'))
    return float(val)

@st.cache_data(ttl=3600) # Cache de 1 hora para a base da NFL (pesada)
def get_sleeper_players():
    res = requests.get("https://api.sleeper.app/v1/players/nfl")
    players = res.json()
    return {f"{v['first_name']} {v['last_name']}": k for k, v in players.items() if v.get('active')}

# --- CORE DO MOTOR DE CÁLCULO ---
def calculate_war_room_score(df):
    def score_row(row):
        adp_real = row.get('ADP', 0)
        if adp_real <= 0: adp_real = 210.0
        
        # Base (90% ADP, 8% Média, 2% Proj)
        v_media = row.get('Media_4_Anos', 0) * 0.08
        v_adp = (210 - adp_real) * 0.9
        v_proj = row.get('Proj', 0) * 0.02
        score_base = v_media + v_adp + v_proj

        # Multiplicador Dinâmico por Performance
        pos = str(row.get('FantPos', '')).upper().strip()
        perf_factor = min(1.0, row.get('Media_4_Anos', 0) / 120)

        if pos in ['RB', 'WR']: mult = 1.3 + (0.5 * perf_factor)
        elif pos in ['QB', 'TE']: mult = 1.2 + (0.25 * perf_factor)
        elif pos in ['DEF', 'K']: mult = 0.7 + (0.2 * perf_factor)
        else: mult = 1.0
        
        return score_base * mult

    df['Score_Final'] = df.apply(score_row, axis=1)
    return df

# --- INTERFACE STREAMLIT ---
st.title("🏈 Fantasy War Room 2026")
st.sidebar.header("Configurações do Draft")

draft_id = st.sidebar.text_input("Sleeper Draft ID", value="1314740945048043520")
refresh = st.sidebar.button("🔄 Atualizar Draft")

# 1. Conectar aos Dados (Google Sheets)
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_raw = conn.read(spreadsheet=st.secrets["spreadsheet_url"]) # URL nas Secrets
    
    # Limpeza
    for col in ['Proj', 'ADP', 'Media_4_Anos']:
        df_raw[col] = df_raw[col].apply(clean_num)
    
    # 2. Sincronizar Sleeper
    name_to_id = get_sleeper_players()
    picks_res = requests.get(f"https://api.sleeper.app/v1/draft/{draft_id}/picks")
    picked_ids = [p['player_id'] for p in picks_res.json()]
    
    # 3. Processar Recomendações
    df_scored = calculate_war_room_score(df_raw)
    df_scored['sleeper_id'] = df_scored['Player'].map(name_to_id)
    
    # Filtrar Disponíveis
    available = df_scored[~df_scored['sleeper_id'].isin(picked_ids)].copy()
    available = available.sort_values(by='Score_Final', ascending=False)

    # 4. DASHBOARD
    col1, col2, col3 = st.columns(3)
    col1.metric("Pick Atual", len(picked_ids) + 1)
    col2.metric("Jogadores Restantes", len(available))
    col3.metric("Última Pick", picks_res.json()[-1]['metadata']['full_name'] if picked_ids else "Nenhuma")

    st.subheader("🎯 Top Picks Recomendadas")
    
    # Formatação da Tabela para Visualização Clean
    st.dataframe(
        available[['Player', 'FantPos', 'Media_4_Anos', 'ADP', 'Proj', 'Score_Final']].head(20),
        column_config={
            "Score_Final": st.column_config.ProgressColumn("Value Score", format="%.1f", min_value=0, max_value=250),
            "Media_4_Anos": "Média Hist.",
            "Proj": "Proj. 2026"
        },
        hide_index=True,
        use_container_width=True
    )

except Exception as e:
    st.error(f"Aguardando conexão ou erro nos dados: {e}")
    st.info("Certifique-se de configurar a URL da planilha nos Secrets do Streamlit.")
