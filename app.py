import streamlit as st
import pandas as pd
import requests
import unicodedata
import re
import time

# --- 1. CONFIGURAÇÃO INICIAL (Obrigatório ser a primeira linha) ---
st.set_page_config(page_title="War Room 2026", layout="wide", page_icon="🏈")

# --- 2. ESTILO VISUAL (CSS AVANÇADO) ---
st.markdown("""
    <style>
    /* Fundo geral e fontes */
    .stApp { background-color: #0E1117; color: #FAFAFA; }
    
    /* Estilização das Métricas do Topo */
    div[data-testid="stMetric"] {
        background-color: #262730;
        border: 1px solid #4CAF50;
        border-radius: 8px;
        padding: 10px;
        text-align: center;
    }
    div[data-testid="stMetricLabel"] { font-size: 0.9rem; color: #AAAAAA; }
    div[data-testid="stMetricValue"] { font-size: 1.6rem; color: #4CAF50; font-weight: bold; }

    /* Abas (Tabs) */
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        background-color: #1c1e26;
        border-radius: 4px;
        padding: 8px 16px;
        font-size: 0.9rem;
        border: 1px solid #333;
    }
    .stTabs [aria-selected="true"] {
        background-color: #4CAF50 !important;
        color: white !important;
        border-color: #4CAF50 !important;
    }

    /* Tabelas */
    div[data-testid="stDataFrame"] { border: 1px solid #333; border-radius: 5px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. FUNÇÕES DE APOIO ---
def get_player_name(metadata):
    full_name = metadata.get('full_name')
    if full_name: return full_name
    first = metadata.get('first_name', '')
    last = metadata.get('last_name', '')
    name = f"{first} {last}".strip()
    return name if name else "Jogador Desconhecido"

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
        # Mapeia nome -> ID
        return {f"{v['first_name']} {v['last_name']}": k for k, v in players.items() if v.get('active')}
    except: return {}

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
        # Multiplicadores de Posição
        if pos in ['RB', 'WR']: mult_pos = 1.3 + (0.5 * perf_factor)
        elif pos == 'TE': mult_pos = 1.25 + (0.35 * perf_factor)
        elif pos == 'QB': mult_pos = 1.2 + (0.25 * perf_factor)
        elif pos in ['DEF', 'K']: mult_pos = 0.7 + (0.2 * perf_factor)
        else: mult_pos = 1.0
        # Multiplicador de Tier
        tier = row.get('Tier', 14)
        if pd.isna(tier) or tier <= 0: tier = 14
        mult_tier = 1 + max(0, (25 - (tier - 1) * 1.92) / 100)
        return (score_base * mult_pos) * mult_tier
    df['Score_Final'] = df.apply(score_row, axis=1)
    return df

# --- 4. PROCESSAMENTO DE DADOS ---
try:
    # Leitura da Planilha
    sheet_url = st.secrets["spreadsheet_url"]
    csv_url = sheet_url.split('/edit')[0] + '/export?format=csv&t=' + str(int(time.time()))
    df_raw = pd.read_csv(csv_url)

    for col in ['Proj', 'ADP', 'Media_4_Anos', 'Tier']:
        if col in df_raw.columns:
            df_raw[col] = df_raw[col].apply(clean_num)

    name_to_id = get_sleeper_players()
    normalized_sleeper_map = {normalize_name(name): pid for name, pid in name_to_id.items()}

    # --- SIDEBAR LIMPA ---
    with st.sidebar:
        st.header("🏈 War Room Pro")
        
        # Busca em destaque
        search_term = st.text_input("🔍 Buscar Jogador", placeholder="Ex: Mahomes...").lower()
        
        # Botão de atualizar
        if st.button("🔄 Atualizar Dados", type="primary", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.divider()

        # Configurações Escondidas
        with st.expander("⚙️ Configurações do Draft", expanded=False):
            draft_id = st.text_input("ID do Draft", value="1316854024770686976")
            minha_posicao = st.number_input("Minha Posição", 1, 16, 1)
            num_times = st.number_input("Total de Times", 2, 16, 10)

        # Processamento das Picks para o Sidebar
        resp_picks = requests.get(f"https://api.sleeper.app/v1/draft/{draft_id}/picks")
        picks_data = resp_picks.json() if resp_picks.status_code == 200 else []
        
        my_picks_count = {"QB": 0, "RB": 0, "WR": 0, "TE": 0}
        my_roster_display = []

        if picks_data:
            for p in picks_data:
                p_no = p.get('pick_no')
                round_no = ((p_no - 1) // num_times) + 1
                slot_da_pick = ((p_no - 1) % num_times) + 1 if round_no % 2 != 0 else num_times - ((p_no - 1) % num_times)
                
                if slot_da_pick == minha_posicao:
                    meta = p.get('metadata', {})
                    pos = meta.get('position', '??')
                    my_roster_display.append(f"**{pos}** {get_player_name(meta)}")
                    if pos in my_picks_count: my_picks_count[pos] += 1
        
        # Painel de Necessidades Visual
        st.subheader("🎯 Meu Time")
        col_n1, col_n2, col_n3, col_n4 = st.columns(4)
        
        def status_card(col, label, current, target):
            color = "#4CAF50" if current >= target else "#FF4B4B"
            col.markdown(f"""
                <div style="background-color:{color}33; border:1px solid {color}; border-radius:5px; text-align:center; padding:5px;">
                    <small style="color:#DDD">{label}</small><br>
                    <strong style="color:{color}; font-size:1.1rem">{current}</strong>
                </div>
            """, unsafe_allow_html=True)

        status_card(col_n1, "QB", my_picks_count['QB'], 1)
        status_card(col_n2, "RB", my_picks_count['RB'], 2)
        status_card(col_n3, "WR", my_picks_count['WR'], 3)
        status_card(col_n4, "TE", my_picks_count['TE'], 1)

        # Lista do Roster (Compacta)
        if my_roster_display:
            with st.expander("📋 Ver Jogadores Draftados", expanded=True):
                for item in my_roster_display:
                    st.markdown(f"- {item}")
        
        # Histórico (Retrátil para não poluir)
        with st.expander("🕒 Últimas Escolhas", expanded=False):
            if picks_data:
                for p in reversed(picks_data[-5:]):
                    meta = p.get('metadata', {})
                    st.caption(f"#{p['pick_no']} {meta.get('position')} {get_player_name(meta)}")

    # --- LÓGICA CENTRAL ---
    df_scored = calculate_war_room_score(df_raw)
    df_scored['norm_name'] = df_scored['Player'].apply(normalize_name)
    df_scored['sleeper_id'] = df_scored['norm_name'].map(normalized_sleeper_map)

    picked_ids_str = [str(p['player_id']) for p in picks_data]
    picked_names_set = set([normalize_name(get_player_name(p.get('metadata', {}))) for p in picks_data])
    
    available = df_scored[~df_scored['sleeper_id'].astype(str).isin(picked_ids_str)].copy()
    available = available[~available['norm_name'].isin(picked_names_set)]
    
    if search_term:
        available = available[available['norm_name'].str.contains(search_term, na=False)]
    
    available = available.sort_values(by='Score_Final', ascending=False)

    # Power Ranking Data
    ranking_data = []
    if picks_data:
        score_dict = dict(zip(df_scored['sleeper_id'].astype(str), df_scored['Score_Final']))
        slot_scores = {i: 0.0 for i in range(1, num_times + 1)}
        slot_counts = {i: 0 for i in range(1, num_times + 1)}
        for p in picks_data:
            p_no = p.get('pick_no')
            round_no = ((p_no - 1) // num_times) + 1
            slot_da_pick = ((p_no - 1) % num_times) + 1 if round_no % 2 != 0 else num_times - ((p_no - 1) % num_times)
            val = score_dict.get(str(p.get('player_id')), 50.0)
            slot_scores[slot_da_pick] += val
            slot_counts[slot_da_pick] += 1
        for slot, total in slot_scores.items():
            qtd = slot_counts[slot]
            if qtd > 0:
                media = round(total / qtd, 1)
                label = f"S{slot}" # Abreviação para caber no gráfico
                if slot == minha_posicao: label = "VOCÊ"
                ranking_data.append({"Time": label, "Média": media, "Qtd": qtd})
    df_ranking = pd.DataFrame(ranking_data).sort_values(by="Média", ascending=False)

    # --- DASHBOARD HEADER ---
    c1, c2, c3 = st.columns([1, 1, 2])
    c1.metric("PICK ATUAL", len(picks_data) + 1)
    c2.metric("LIVRES", len(available))
    
    last_text = "Draft não iniciado"
    if picks_data:
        last = picks_data[-1]
        m = last.get('metadata', {})
        lp_no = last.get('pick_no')
        lr_no = ((lp_no - 1) // num_times) + 1
        l_slot = ((lp_no - 1) % num_times) + 1 if lr_no % 2 != 0 else num_times - ((lp_no - 1) % num_times)
        last_text = f"{m.get('position')} {get_player_name(m)} (Slot {l_slot})"
    c3.metric("ÚLTIMA ESCOLHA", last_text)

    st.markdown("---")

    # --- ABAS DE DADOS ---
    tabs = st.tabs(["💎 GERAL", "🏈 QB", "🏃 RB", "👐 WR", "🧤 TE", "🛡️ DEF/K", "📊 RANKING"])

    def show_table(data):
        st.dataframe(
            data[['Player', 'FantPos', 'Tier', 'Media_4_Anos', 'ADP', 'Score_Final']].head(30),
            column_config={
                "Player": st.column_config.TextColumn("Jogador", width="large"),
                "FantPos": st.column_config.TextColumn("Pos", width="small"),
                "Tier": st.column_config.NumberColumn("Tier", format="T%d"),
                "Score_Final": st.column_config.ProgressColumn("Score", format="%.0f", min_value=0, max_value=250, help="Potencial calculado"),
                "ADP": st.column_config.NumberColumn("ADP", format="%.1f"),
                "Media_4_Anos": st.column_config.NumberColumn("Méd Pts", format="%.1f")
            },
            hide_index=True, use_container_width=True
        )

    with tabs[0]: # GERAL
        with st.expander("📊 Monitor de Escassez (Tier Drop-off)", expanded=False):
            st.info("Mostra quantos jogadores de elite restam em cada posição.")
            top_tiers = available[available['Tier'] <= 4].copy()
            if not top_tiers.empty:
                scarcity = top_tiers.groupby(['Tier', 'FantPos']).size().unstack(fill_value=0)
                cols_order = [c for c in ['QB', 'RB', 'WR', 'TE'] if c in scarcity.columns]
                st.dataframe(scarcity[cols_order], use_container_width=True)
            else:
                st.write("Sem jogadores de elite (Tier 1-4) disponíveis.")
        show_table(available)

    with tabs[1]: show_table(available[available['FantPos'] == 'QB'])
    with tabs[2]: show_table(available[available['FantPos'] == 'RB'])
    with tabs[3]: show_table(available[available['FantPos'] == 'WR'])
    with tabs[4]: show_table(available[available['FantPos'] == 'TE'])
    with tabs[5]: show_table(available[available['FantPos'].isin(['DEF','K'])])
    
    with tabs[6]: # RANKING
        st.subheader("Quem está draftando melhor?")
        if not df_ranking.empty:
            df_plot = df_ranking.sort_values(by="Média", ascending=False).set_index("Time")
            # Gráfico limpo
            st.bar_chart(df_plot["Média"], color="#4CAF50")
            st.caption("Baseado na média de Valor Agregado (Score) por escolha.")
            st.table(df_ranking)
        else:
            st.info("Aguardando picks...")

except Exception as e:
    st.error(f"Erro no sistema: {e}")
