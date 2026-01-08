import streamlit as st
import pandas as pd
import requests
import unicodedata
import re
from streamlit_gsheets import GSheetsConnection

# Configuração da Página
st.set_page_config(page_title="Fantasy War Room 2026", layout="wide", page_icon="🏈")

# --- FUNÇÕES DE LIMPEZA E NORMALIZAÇÃO ---
def clean_num(val):
    if pd.isna(val) or val == 0: return 0.0
    if isinstance(val, str):
        return float(val.replace('.', '').replace(',', '.'))
    return float(val)

def normalize_name(name):
    if not isinstance(name, str): return ""
    # Remove acentos
    name = "".join(c for c in unicodedata.normalize('NFD', name) if unicodedata.category(c) != 'Mn')
    # Remove TUDO que não seja letra (pontos, espaços extras, números, símbolos)
    name = re.sub(r'[^a-zA-Z]', '', name.lower())
    # Remove sufixos comuns
    for suffix in ['jr', 'iii', 'ii', 'sr', 'iv']:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return name.strip()

@st.cache_data(ttl=3600)
def get_sleeper_players():
    res = requests.get("https://api.sleeper.app/v1/players/nfl")
    players = res.json()
    return {f"{v['first_name']} {v['last_name']}": k for k, v in players.items() if v.get('active')}

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

# --- INTERFACE PRINCIPAL ---
st.title("🏈 Fantasy War Room 2026")
st.sidebar.header("Configurações")

draft_id = st.sidebar.text_input("Sleeper Draft ID", value="1314740945048043520")
if st.sidebar.button("🔄 Forçar Atualização"):
    st.cache_data.clear() # Limpa o cache para garantir dados frescos
    st.rerun() # Recarrega o app

try:
    # 1. Conexão com Dados
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_raw = conn.read(spreadsheet=st.secrets["spreadsheet_url"])
    
    for col in ['Proj', 'ADP', 'Media_4_Anos']:
        df_raw[col] = df_raw[col].apply(clean_num)
    
    # 2. Sincronização Sleeper (ID e Nomes)
    name_to_id = get_sleeper_players()
    normalized_sleeper_map = {normalize_name(name): pid for name, pid in name_to_id.items()}
    
    picks_res = requests.get(f"https://api.sleeper.app/v1/draft/{draft_id}/picks")
    picks_data = picks_res.json()
    picked_ids = [p['player_id'] for p in picks_data]
    picked_names_norm = [normalize_name(p.get('metadata', {}).get('full_name', '')) for p in picks_data]
    
    # 3. Processamento
    df_scored = calculate_war_room_score(df_raw)
    df_scored['norm_name'] = df_scored['Player'].apply(normalize_name)
    df_scored['sleeper_id'] = df_scored['norm_name'].map(normalized_sleeper_map)
    
    # Filtragem Inteligente (ID ou Nome)
    available = df_scored[
        (~df_scored['sleeper_id'].isin(picked_ids)) & 
        (~df_scored['norm_name'].isin(picked_names_norm))
    ].copy()
    available = available.sort_values(by='Score_Final', ascending=False)

    # 4. DASHBOARD
    col1, col2, col3 = st.columns(3)
    total_picks = len(picks_data)
    col1.metric("Pick Atual", total_picks + 1)
    col2.metric("Disponíveis", len(available))
    
    if total_picks > 0:
        last_pick = picks_data[-1]
        nome_ultimo = last_pick.get('metadata', {}).get('full_name', f"ID: {last_pick['player_id']}")
        col3.metric("Última Pick", nome_ultimo)
    else:
        col3.metric("Última Pick", "Nenhuma")

    st.subheader("🎯 Melhores Disponíveis (Algoritmo v4.0)")
    st.dataframe(
        available[['Player', 'FantPos', 'Media_4_Anos', 'ADP', 'Proj', 'Score_Final']].head(25),
        column_config={
            "Score_Final": st.column_config.ProgressColumn("Value Score", format="%.1f", min_value=0, max_value=250),
            "Media_4_Anos": "Média Hist.",
            "Proj": "Proj. 2026"
        },
        hide_index=True,
        use_container_width=True
    )

except Exception as e:
    st.error(f"Erro na sincronização: {e}")
