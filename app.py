import streamlit as st
import pandas as pd
import requests
import unicodedata
import re
from streamlit_gsheets import GSheetsConnection

# Configuração da Página
st.set_page_config(page_title="War Room 2026", layout="wide", page_icon="🏈")

# --- ESTILO CSS ---
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
    try:
        res = requests.get("https://api.sleeper.app/v1/players/nfl")
        players = res.json()
        mapping = {f"{v['first_name']} {v['last_name']}": k for k, v in players.items() if v.get('active')}
        mapping["Lamar Jackson"] = "4881"
        return mapping
    except:
        return {"Lamar Jackson": "4881"}

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
        if pos in ['RB', 'WR']: mult_pos = 1.3 + (0.5 * perf_factor)
        elif pos == 'TE': mult_pos = 1.25 + (0.35 * perf_factor)
        elif pos == 'QB': mult_pos = 1.2 + (0.25 * perf_factor)
        elif pos in ['DEF', 'K']: mult_pos = 0.7 + (0.2 * perf_factor)
        else: mult_pos = 1.0
        tier = row.get('Tier', 14)
        if pd.isna(tier) or tier <= 0: tier = 14
        bonus_tier = max(0, (25 - (tier - 1) * 1.92) / 100)
        mult_tier = 1 + bonus_tier
        return (score_base * mult_pos) * mult_tier
    df['Score_Final'] = df.apply(score_row, axis=1)
    return df

# --- PROCESSAMENTO ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_raw = conn.read(spreadsheet=st.secrets["spreadsheet_url"])
    for col in ['Proj', 'ADP', 'Media_4_Anos', 'Tier']:
        if col in df_raw.columns:
            df_raw[col] = df_raw[col].apply(clean_num)

    name_to_id = get_sleeper_players()
    normalized_sleeper_map = {normalize_name(name): pid for name, pid in name_to_id.items()}

    # 1. Busca Picks primeiro para alimentar a Sidebar
    draft_id_input = "1316854024770686976" # Valor padrão
    
    # --- SIDEBAR ---
    with st.sidebar:
        st.title("🏈 War Room Config")
        draft_id = st.text_input("Sleeper Draft ID", value=draft_id_input)
        
        if st.button("🔄 Atualizar"):
            st.cache_data.clear()
            st.rerun()

        st.divider()
        st.subheader("📋 Meu Roster")
        
        # BUSCA DADOS DO SLEEPER
        resp_picks = requests.get(f"https://api.sleeper.app/v1/draft/{draft_id}/picks")
        picks_data = resp_picks.json() if resp_picks.status_code == 200 else []
        
        if picks_data:
            # Mapeia quais roster_ids existem e que nomes eles têm no metadata
            roster_map = {}
            for p in picks_data:
                rid = p.get('roster_id')
                if rid not in roster_map:
                    # Tenta achar um nome amigável para esse Slot
                    meta = p.get('metadata', {})
                    nome_display = meta.get('display_name') or meta.get('team_name') or f"Time Slot {rid}"
                    roster_map[rid] = nome_display
            
            # Dropdown para você escolher qual desses times é o seu
            escolha_roster = st.selectbox(
                "Quem é você no Draft?", 
                options=list(roster_map.keys()), 
                format_func=lambda x: roster_map[x]
            )
            
            # Filtra e exibe
            my_picks = [p for p in picks_data if p.get('roster_id') == escolha_roster]
            my_picks_sorted = sorted(my_picks, key=lambda x: x.get('metadata', {}).get('position', ''))
            
            for p in my_picks_sorted:
                p_name = p.get('metadata', {}).get('full_name', 'Player')
                p_pos = p.get('metadata', {}).get('position', '??')
                st.write(f"**{p_pos}**: {p_name}")
        else:
            st.write("Aguardando picks iniciais...")

    # 3. Disponibilidade e Dashboard
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

    # --- UI DASHBOARD ---
    col1, col2, col3 = st.columns([1, 1, 2])
    col1.metric("Pick Atual", len(picks_data) + 1)
    col2.metric("Disponíveis", len(available))
    if picks_data:
        last = picks_data[-1]
        nome_l = last.get('metadata', {}).get('full_name', f"ID: {last['player_id']}")
        col3.metric("Última Pick", nome_l)

    st.divider()
    tabs = st.tabs(["💎 Geral", "🏈 QB", "🏃 RB", "👐 WR", "🧤 TE", "🔄 FLEX", "🛡️ DEF/K"])

    def show_table(data):
        st.dataframe(
            data[['Player', 'FantPos', 'Tier', 'Media_4_Anos', 'ADP', 'Score_Final']].head(30),
            column_config={
                "Score_Final": st.column_config.ProgressColumn("Value Score", format="%.1f", min_value=0, max_value=250, color="green"),
                "Tier": st.column_config.NumberColumn("Tier", format="T%d"),
                "Media_4_Anos": "Média Hist.",
                "ADP": st.column_config.NumberColumn("ADP", format="%.1f"),
            },
            hide_index=True, use_container_width=True
        )

    for i, t in enumerate(tabs):
        with t:
            if i == 0: show_table(available)
            elif i == 1: show_table(available[available['FantPos'] == 'QB'])
            elif i == 2: show_table(available[available['FantPos'] == 'RB'])
            elif i == 3: show_table(available[available['FantPos'] == 'WR'])
            elif i == 4: show_table(available[available['FantPos'] == 'TE'])
            elif i == 5: show_table(available[available['FantPos'].isin(['RB', 'WR', 'TE'])])
            elif i == 6: show_table(available[available['FantPos'].isin(['DEF', 'K'])])

except Exception as e:
    st.error(f"Erro: {e}")
