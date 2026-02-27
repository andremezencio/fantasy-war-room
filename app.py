import streamlit as st
import pandas as pd
import requests
import unicodedata
import re
import time

# --- 1. CONFIGURAÇÃO INICIAL ---
st.set_page_config(page_title="War Room 2026", layout="wide", page_icon="🏈")

# --- 2. ESTILO VISUAL ---
st.markdown("""
    <style>
    div[data-testid="stMetric"] {
        background-color: #f0f2f6;
        border: 1px solid #d0d0d0;
        border-radius: 8px;
        padding: 10px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
    }
    @media (prefers-color-scheme: dark) {
        div[data-testid="stMetric"] { background-color: #262730; border: 1px solid #444; }
    }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { padding: 8px 20px; font-weight: 600; border-radius: 4px; }
    .stTabs [aria-selected="true"] { border-bottom: 3px solid #4CAF50 !important; color: #4CAF50 !important; }
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
        if pos in ['RB', 'WR']: mult_pos = 1.3 + (0.5 * perf_factor)
        elif pos == 'TE': mult_pos = 1.25 + (0.35 * perf_factor)
        elif pos == 'QB': mult_pos = 1.2 + (0.25 * perf_factor)
        elif pos in ['DEF', 'K']: mult_pos = 0.7 + (0.2 * perf_factor)
        else: mult_pos = 1.0
        tier = row.get('Tier', 14)
        if pd.isna(tier) or tier <= 0: tier = 14
        mult_tier = 1 + max(0, (25 - (tier - 1) * 1.92) / 100)
        return (score_base * mult_pos) * mult_tier
    df['Score_Final'] = df.apply(score_row, axis=1)
    return df

# --- 4. CARREGAMENTO DE DADOS ---
try:
    sheet_url = st.secrets["spreadsheet_url"]
    csv_url = sheet_url.split('/edit')[0] + '/export?format=csv&t=' + str(int(time.time()))
    df_raw = pd.read_csv(csv_url)

    for col in ['Proj', 'ADP', 'Media_4_Anos', 'Tier']:
        if col in df_raw.columns:
            df_raw[col] = df_raw[col].apply(clean_num)

    name_to_id = get_sleeper_players()
    normalized_sleeper_map = {normalize_name(name): pid for name, pid in name_to_id.items()}

    # --- SIDEBAR OTIMIZADA ---
    with st.sidebar:
        st.header("🏈 War Room Pro")
        
        search_term = st.text_input("🔍 Buscar Jogador", placeholder="Nome...").lower()
        st.markdown("---")

        with st.expander("⚙️ Configurações", expanded=True):
            # O .strip() remove espaços vazios no final caso você cole errado
            draft_id = st.text_input("ID do Draft", value="").strip()
            minha_posicao = st.number_input("Minha Posição", 1, 16, 1)
            num_times = st.number_input("Total de Times", 2, 16, 10)
            
            # Botão movido para DEPOIS de você inserir o ID
            if st.button("🔄 Atualizar Agora", type="primary", use_container_width=True):
                st.cache_data.clear()
                st.rerun()

        # Processamento Picks com Tratamento de Erro
        resp_picks = requests.get(f"https://api.sleeper.app/v1/draft/{draft_id}/picks")
        
        picks_data = []
        if resp_picks.status_code == 200:
            picks_data = resp_picks.json()
            if not picks_data and draft_id:
                st.warning("⚠️ O ID está correto, mas o draft ainda não tem escolhas (ou pode ser um ID de Liga em vez de Draft).")
        else:
            st.error("🚨 Erro de API. Verifique se o ID do Draft está correto.")
        
        my_picks_count = {"QB": 0, "RB": 0, "WR": 0, "TE": 0, "K": 0, "DEF": 0}
        my_roster_list = []

        if picks_data:
            for p in picks_data:
                p_no = p.get('pick_no')
                round_no = ((p_no - 1) // num_times) + 1
                slot_da_pick = ((p_no - 1) % num_times) + 1 if round_no % 2 != 0 else num_times - ((p_no - 1) % num_times)
                
                if slot_da_pick == minha_posicao:
                    meta = p.get('metadata', {})
                    pos = meta.get('position', '??')
                    if pos == 'DST': pos = 'DEF' 
                    my_roster_list.append(f"R{round_no}: {pos} {get_player_name(meta)}")
                    if pos in my_picks_count: my_picks_count[pos] += 1
        
        # --- INTELIGÊNCIA DO ROSTER ---
        qb_start = min(1, my_picks_count["QB"])
        rb_start = min(1, my_picks_count["RB"])
        wr_start = min(1, my_picks_count["WR"])
        te_start = min(1, my_picks_count["TE"])
        k_start = min(1, my_picks_count["K"])
        def_start = min(1, my_picks_count["DEF"])
        
        leftover_flex = max(0, my_picks_count["RB"] - 1) + max(0, my_picks_count["WR"] - 1) + max(0, my_picks_count["TE"] - 1)
        flex_start = min(1, leftover_flex)
        
        total_drafted = sum(my_picks_count.values())
        total_starters = qb_start + rb_start + wr_start + te_start + flex_start + k_start + def_start
        bench = total_drafted - total_starters

        st.subheader("🎯 Meu Elenco")
        c1, c2 = st.columns(2)
        
        def stat_box(col, label, val, req):
            color = "green" if val >= req else ("orange" if val > 0 else "red")
            col.markdown(f":{color}[**{label}** {val}/{req}]")

        stat_box(c1, "QB", qb_start, 1)
        stat_box(c2, "FLEX", flex_start, 1)
        stat_box(c1, "RB", rb_start, 1)
        stat_box(c2, "K", k_start, 1)
        stat_box(c1, "WR", wr_start, 1)
        stat_box(c2, "DEF", def_start, 1)
        stat_box(c1, "TE", te_start, 1)
        stat_box(c2, "BN", bench, 2)

        if my_roster_list:
            with st.expander("Ver Jogadores", expanded=False):
                for item in my_roster_list: st.caption(item)
        
        with st.expander("🕒 Últimas Escolhas", expanded=False):
            if picks_data:
                for p in reversed(picks_data[-5:]):
                    meta = p.get('metadata', {})
                    st.write(f"#{p['pick_no']} **{meta.get('position')}** {get_player_name(meta)}")

    # --- LÓGICA DE DADOS ---
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

    # Ranking & Board Data
    ranking_data = []
    board_data = []
    
    if picks_data:
        score_dict = dict(zip(df_scored['sleeper_id'].astype(str), df_scored['Score_Final']))
        slot_scores = {i: 0.0 for i in range(1, num_times + 1)}
        slot_counts = {i: 0 for i in range(1, num_times + 1)}
        
        for p in picks_data:
            p_no = p.get('pick_no')
            round_no = ((p_no - 1) // num_times) + 1
            if round_no % 2 != 0: slot = ((p_no - 1) % num_times) + 1
            else: slot = num_times - ((p_no - 1) % num_times)
            
            val = score_dict.get(str(p.get('player_id')), 50.0)
            slot_scores[slot] += val
            slot_counts[slot] += 1
            
            meta = p.get('metadata', {})
            short_name = f"{meta.get('position')} {meta.get('last_name', '')}"
            board_data.append({"Round": round_no, "Slot": slot, "Pick": short_name})
            
        for slot, total in slot_scores.items():
            qtd = slot_counts[slot]
            if qtd > 0:
                media = round(total / qtd, 1)
                label = "VOCÊ" if slot == minha_posicao else f"S{slot}"
                ranking_data.append({"Time": label, "Média": media, "Qtd": qtd})
    
    df_ranking = pd.DataFrame(ranking_data, columns=["Time", "Média", "Qtd"])
    if not df_ranking.empty:
        df_ranking = df_ranking.sort_values(by="Média", ascending=False)

    # --- TOP METRICS ---
    col_m1, col_m2, col_m3 = st.columns([1, 1, 2])
    col_m1.metric("Pick Atual", len(picks_data) + 1)
    col_m2.metric("Disponíveis", len(available))
    
    last_text = "-"
    if picks_data:
        last = picks_data[-1]
        m = last.get('metadata', {})
        last_text = f"{m.get('position')} {get_player_name(m)}"
    col_m3.metric("Última Escolha", last_text)

    st.write("")

    # --- ABAS ---
    tabs = st.tabs(["💎 GERAL", "🗺️ BOARD", "🏈 QB", "🏃 RB", "👐 WR", "🧤 TE", "🛡️ DEF/K", "📊 RANKING"])

    def show_table(data):
        st.dataframe(
            data[['Player', 'FantPos', 'Tier', 'Media_4_Anos', 'ADP', 'Score_Final']].head(30),
            column_config={
                "Player": st.column_config.TextColumn("Jogador", width="large"),
                "FantPos": st.column_config.TextColumn("Pos", width="small"),
                "Tier": st.column_config.NumberColumn("Tier", format="T%d"),
                "Score_Final": st.column_config.ProgressColumn("Score", format="%.0f", min_value=0, max_value=250),
                "Media_4_Anos": st.column_config.NumberColumn("Méd Pts", format="%.1f")
            },
            hide_index=True, use_container_width=True
        )

    with tabs[0]: 
        with st.expander("📉 Monitor de Escassez (Tier Drop-off)", expanded=False):
            top_tiers = available[available['Tier'] <= 4].copy()
            if not top_tiers.empty:
                scarcity = top_tiers.groupby(['Tier', 'FantPos']).size().unstack(fill_value=0)
                cols_order = [c for c in ['QB', 'RB', 'WR', 'TE'] if c in scarcity.columns]
                st.dataframe(scarcity[cols_order], use_container_width=True)
            else:
                st.caption("Nenhum jogador Tier 1-4 restante.")
        show_table(available)

    with tabs[1]: 
        st.subheader("Mapa do Draft")
        if board_data:
            df_board = pd.DataFrame(board_data)
            pivot_board = df_board.pivot(index="Round", columns="Slot", values="Pick")
            for i in range(1, num_times + 1):
                if i not in pivot_board.columns: pivot_board[i] = ""
            pivot_board = pivot_board.reindex(sorted(pivot_board.columns), axis=1)
            st.dataframe(pivot_board, use_container_width=True)
        else:
            st.info("O Board será preenchido após a primeira escolha.")

    with tabs[2]: show_table(available[available['FantPos'] == 'QB'])
    with tabs[3]: show_table(available[available['FantPos'] == 'RB'])
    with tabs[4]: show_table(available[available['FantPos'] == 'WR'])
    with tabs[5]: show_table(available[available['FantPos'] == 'TE'])
    with tabs[6]: show_table(available[available['FantPos'].isin(['DEF','K'])])
    
    with tabs[7]: 
        st.subheader("Ranking de Eficiência")
        if not df_ranking.empty:
            df_plot = df_ranking.set_index("Time")
            st.bar_chart(df_plot["Média"], color="#4CAF50")
            st.table(df_ranking)
        else:
            st.info("O gráfico aparecerá após a primeira escolha.")

except Exception as e:
    st.error(f"Erro: {e}")
