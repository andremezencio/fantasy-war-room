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
        return mapping
    except:
        return {}

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

# --- PROCESSAMENTO PRINCIPAL ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_raw = conn.read(spreadsheet=st.secrets["spreadsheet_url"])
    for col in ['Proj', 'ADP', 'Media_4_Anos', 'Tier']:
        if col in df_raw.columns:
            df_raw[col] = df_raw[col].apply(clean_num)

    name_to_id = get_sleeper_players()
    normalized_sleeper_map = {normalize_name(name): pid for name, pid in name_to_id.items()}

    # --- SIDEBAR ---
    with st.sidebar:
        st.title("🏈 War Room Config")
        draft_id = st.text_input("Sleeper Draft ID", value="1316854024770686976")
        minha_posicao = st.number_input("Sua Posição no Draft (#)", min_value=1, max_value=16, value=1)
        num_times = st.number_input("Total de Times no Draft", min_value=2, max_value=16, value=10)
        
        if st.button("🔄 Atualizar"):
            st.cache_data.clear()
            st.rerun()

        st.divider()
        st.subheader("📋 Meu Roster")
        
        resp_picks = requests.get(f"https://api.sleeper.app/v1/draft/{draft_id}/picks")
        picks_data = resp_picks.json() if resp_picks.status_code == 200 else []
        
        my_picks = []
        if picks_data:
            for p in picks_data:
                p_no = p.get('pick_no')
                round_no = ((p_no - 1) // num_times) + 1
                if round_no % 2 != 0: slot_da_pick = ((p_no - 1) % num_times) + 1
                else: slot_da_pick = num_times - ((p_no - 1) % num_times)
                
                if slot_da_pick == minha_posicao:
                    my_picks.append(p)
            
            if my_picks:
                my_picks_sorted = sorted(my_picks, key=lambda x: x.get('metadata', {}).get('position', ''))
                for p in my_picks_sorted:
                    meta = p.get('metadata', {})
                    p_name = meta.get('full_name') or f"{meta.get('first_name', '')} {meta.get('last_name', '')}".strip() or "Jogador"
                    p_pos = meta.get('position', '??')
                    st.write(f"**{p_pos}**: {p_name}")
            else:
                st.info(f"Aguardando sua vez na posição {minha_posicao}...")

        st.divider()
        st.subheader("🕒 Picks Recentes")
        if picks_data:
            for p in reversed(picks_data[-5:]):
                m = p.get('metadata', {})
                st.caption(f"#{p['pick_no']} - {m.get('position')} {m.get('full_name') or m.get('last_name')}")

    # --- CÁLCULO DE DISPONIBILIDADE E POWER RANKING ---
    df_scored = calculate_war_room_score(df_raw)
    df_scored['norm_name'] = df_scored['Player'].apply(normalize_name)
    df_scored['sleeper_id'] = df_scored['norm_name'].map(normalized_sleeper_map)

    picked_ids_str = [str(p['player_id']) for p in picks_data]
    picked_names_set = set([normalize_name(p.get('metadata', {}).get('full_name', '')) for p in picks_data])
    
    available = df_scored[~df_scored['sleeper_id'].astype(str).isin(picked_ids_str)].copy()
    available = available[~available['norm_name'].isin(picked_names_set)]
    available = available.sort_values(by='Score_Final', ascending=False)

    # Lógica Power Ranking
    ranking_data = []
    if picks_data:
        score_dict = dict(zip(df_scored['sleeper_id'].astype(str), df_scored['Score_Final']))
        roster_scores = {}
        for p in picks_data:
            rid = p.get('roster_id') or "N/A"
            pid = str(p.get('player_id'))
            roster_scores[rid] = roster_scores.get(rid, 0) + score_dict.get(pid, 50.0)
        
        for rid, total in roster_scores.items():
            nome_label = f"Time {rid}"
            if str(rid) == str(minha_posicao): nome_label = "🏆 SEU TIME"
            ranking_data.append({"Time": nome_label, "Soma Score": round(total, 1)})
    
    df_ranking = pd.DataFrame(ranking_data).sort_values(by="Soma Score", ascending=False)

    # --- UI DASHBOARD ---
    c1, c2, c3 = st.columns([1, 1, 2])
    c1.metric("Pick Atual", len(picks_data) + 1)
    c2.metric("Disponíveis", len(available))
    if picks_data:
        lm = picks_data[-1].get('metadata', {})
        c3.metric("Última Pick", lm.get('full_name') or lm.get('last_name') or "N/A")

    st.divider()
    t = st.tabs(["💎 Geral", "🏈 QB", "🏃 RB", "👐 WR", "🧤 TE", "🔄 FLEX", "🛡️ DEF/K", "📊 Power Ranking"])

    def show_table(data):
        st.dataframe(
            data[['Player', 'FantPos', 'Tier', 'Media_4_Anos', 'ADP', 'Score_Final']].head(30),
            column_config={
                "Score_Final": st.column_config.ProgressColumn("Value Score", format="%.1f", min_value=0, max_value=250, color="green"),
                "Tier": st.column_config.NumberColumn("Tier", format="T%d"),
                "ADP": st.column_config.NumberColumn("ADP", format="%.1f"),
            },
            hide_index=True, use_container_width=True
        )

    with t[0]: show_table(available)
    with t[1]: show_table(available[available['FantPos'] == 'QB'])
    with t[2]: show_table(available[available['FantPos'] == 'RB'])
    with t[3]: show_table(available[available['FantPos'] == 'WR'])
    with t[4]: show_table(available[available['FantPos'] == 'TE'])
    with t[5]: show_table(available[available['FantPos'].isin(['RB', 'WR', 'TE'])])
    with t[6]: show_table(available[available['FantPos'].isin(['DEF', 'K'])])
    with t[7]:
        st.subheader("Classificação do Draft (Soma de Scores)")
        st.table(df_ranking)

except Exception as e:
    st.error(f"Erro: {e}")
