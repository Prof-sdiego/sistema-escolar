import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
import time
from streamlit_autorefresh import st_autorefresh
import google.generativeai as genai

# --- CONFIGURAÇÕES GERAIS ---
st.set_page_config(page_title="Ocorrência Digital", layout="wide", page_icon="🏫")

# CSS para esconder menus e preparar impressão
estilo_css = """
<style>
    #MainMenu {visibility: hidden;} 
    footer {visibility: hidden;} 
    header {visibility: hidden;}
    
    /* Estilo para a Ficha de Impressão */
    @media print {
        body * {
            visibility: hidden;
        }
        .area-impressao, .area-impressao * {
            visibility: visible;
        }
        .area-impressao {
            position: absolute;
            left: 0;
            top: 0;
            width: 100%;
        }
    }
    .card-impressao {
        border: 2px solid #333;
        padding: 30px;
        background-color: white;
        color: black;
        font-family: 'Arial', sans-serif;
        margin: 20px 0;
    }
</style>
"""
st.markdown(estilo_css, unsafe_allow_html=True)

# --- SOM (Suave para todas, Alarme para Grave) ---
def tocar_som(tipo="normal"):
    # Som suave (Ding)
    sound_url = "https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"
    
    # Injeta audio autoplay
    st.markdown(f"""
        <audio autoplay>
            <source src="{sound_url}" type="audio/mp3">
        </audio>
    """, unsafe_allow_html=True)

# --- CONEXÃO ---
@st.cache_resource
def conectar():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(st.secrets["service_account_info"]), scope)
    client = gspread.authorize(creds)
    return client.open("Dados_Escolares")

# --- AUTO-DETECÇÃO IA ---
@st.cache_resource
def configurar_ia_automatica():
    try:
        genai.configure(api_key=st.secrets["gemini_key"])
        todos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        escolhido = next((m for m in todos if "flash" in m and "1.5" in m), None)
        if not escolhido: escolhido = next((m for m in todos if "flash" in m), None)
        if not escolhido: escolhido = next((m for m in todos if "gemini" in m), todos[0] if todos else None)
        return escolhido
    except: return None

nome_modelo_ativo = configurar_ia_automatica()

# --- DADOS ---
def carregar_alertas(): 
    try:
        sheet = conectar().worksheet("Alertas")
        d = sheet.get_all_records()
        return pd.DataFrame(d) if d else pd.DataFrame(columns=["Data", "Turma", "Professor", "Status"])
    except: return pd.DataFrame(columns=["Data", "Turma", "Professor", "Status"])

@st.cache_data(ttl=60) 
def carregar_ocorrencias_cache(): 
    try:
        sheet = conectar().sheet1
        d = sheet.get_all_records()
        return pd.DataFrame(d) if d else pd.DataFrame(columns=["Data", "Aluno", "Turma", "Professor", "Descricao", "Acao_Sugerida", "Intervencao", "Status_Gestao"])
    except: return pd.DataFrame()

@st.cache_data(ttl=3600)
def carregar_professores(): 
    try:
        sheet = conectar().worksheet("Professores")
        d = sheet.get_all_records()
        return pd.DataFrame(d)
    except: return pd.DataFrame()

# --- ESCRITA ---
def limpar_cache(): st.cache_data.clear()

def salvar_ocorrencia(alunos_lista, turma, prof, desc, acao, intervencao=""):
    try:
        sheet = conectar().sheet1
        data = datetime.now().strftime("%Y-%m-%d %H:%M")
        # CORREÇÃO DA VÍRGULA: Garante que é uma lista plana
        for aluno in alunos_lista:
            aluno_limpo = aluno.strip()
            if aluno_limpo:
                sheet.append_row([data, aluno_limpo, turma, prof, desc, acao, intervencao, "Pendente"])
        limpar_cache()
        return True
    except: return False

def atualizar_status_gestao(aluno, data, novo_status, intervencao_texto=None):
    try:
        wb = conectar(); sheet = wb.sheet1; cell = sheet.find(aluno)
        if cell:
            sheet.update_cell(cell.row, 8, novo_status)
            if intervencao_texto: sheet.update_cell(cell.row, 7, intervencao_texto)
        limpar_cache()
    except: pass

def excluir_ocorrencia(aluno, desc_trecho):
    try:
        wb = conectar(); sheet = wb.sheet1; dados = sheet.get_all_records()
        for i, row in enumerate(dados):
            if row['Aluno'] == aluno and desc_trecho in row['Descricao']:
                sheet.delete_rows(i + 2); break
        limpar_cache()
    except: pass

def salvar_alerta(turma, prof):
    conectar().worksheet("Alertas").append_row([datetime.now().strftime("%H:%M"), turma, prof, "Pendente"])

def atualizar_alerta_status(turma, novo_status):
    try:
        wb = conectar(); sheet = wb.worksheet("Alertas"); dados = sheet.get_all_records()
        for i, row in enumerate(dados):
            if row['Turma'] == turma and row['Status'] != "Resolvido":
                sheet.update_cell(i + 2, 4, novo_status); break
    except: pass

# --- IA ---
def consultar_ia(descricao, turma):
    if not nome_modelo_ativo: return "Erro Config", "IA Indisponível"
    prompt = f"""
    Você é um especialista do programa CONVIVA SP (Protocolo 179).
    Analise a ocorrência escolar.
    Dados: Turma {turma} | Fato: "{descricao}"
    Classifique a GRAVIDADE em: ALTA, MÉDIA, BAIXA.
    Sugira AÇÃO (curta) focada na mediação.
    Responda formato: GRAVIDADE: [G] AÇÃO: [A]
    """
    try:
        safety = [{"category": c, "threshold": "BLOCK_NONE"} for c in ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"]]
        modelo = genai.GenerativeModel(nome_modelo_ativo)
        resp = modelo.generate_content(prompt, safety_settings=safety)
        texto = resp.text
        g, a = "Média", texto
        if "GRAVIDADE:" in texto:
            parts = texto.split("AÇÃO:")
            g = parts[0].replace("GRAVIDADE:", "").strip()
            a = parts[1].strip() if len(parts) > 1 else texto
        return g, a
    except: return "Média", "Erro IA"

# --- LOGIN PERSISTENTE ---
params = st.query_params
if "prof_logado" in params:
    st.session_state.prof_logado = True
    st.session_state.prof_nome = params["prof_nome"]

if 'prof_logado' not in st.session_state: st.session_state.prof_logado = False
if 'prof_nome' not in st.session_state: st.session_state.prof_nome = ""
if 'panico_mode' not in st.session_state: st.session_state.panico_mode = False
# Estado para controlar impressão
if 'dados_impressao' not in st.session_state: st.session_state.dados_impressao = None

# --- INTERFACE ---
st.title("🏫 Ocorrência Digital")
menu = st.sidebar.radio("Menu", ["Acesso Professor", "Painel Gestão"])

# ================= PROFESSOR =================
if menu == "Acesso Professor":
    if not st.session_state.prof_logado:
        with st.form("login_form"):
            st.write("### 🔐 Acesso Restrito")
            ln = st.text_input("Nome")
            lc = st.text_input("Código", type="password")
            if st.form_submit_button("Entrar no Sistema"):
                df = carregar_professores()
                if not df.empty:
                    df['Codigo'] = df['Codigo'].astype(str)
                    if not df[(df['Nome'] == ln) & (df['Codigo'] == lc)].empty:
                        st.session_state.prof_logado = True
                        st.session_state.prof_nome = ln
                        st.query_params["prof_logado"] = "true"
                        st.query_params["prof_nome"] = ln
                        st.rerun()
                    else: st.error("Dados inválidos.")
    else:
        col_h1, col_h2 = st.columns([4,1])
        col_h1.success(f"👤 Olá, **{st.session_state.prof_nome}**")
        if col_h2.button("Sair"):
            st.session_state.prof_logado = False
            st.query_params.clear()
            st.rerun()

        tab_reg, tab_hist = st.tabs(["📝 Nova Ocorrência", "🗂️ Meus Registros"])

        with tab_reg:
            c1, c2 = st.columns([3,1])
            c1.warning("⚠️ Botão de Pânico apenas para **Emergências Graves**.")
            if c2.button("🚨 CHAMAR GESTÃO", type="primary"): st.session_state.panico_mode = True
            
            if st.session_state.panico_mode:
                with st.form("panico"):
                    st.error("CONFIRMAR EMERGÊNCIA?")
                    t = st.selectbox("Sala:", ["6A","6B","7A","7B","8A","8B","9A","9B"])
                    if st.form_submit_button("CONFIRMAR"):
                        salvar_alerta(t, st.session_state.prof_nome)
                        st.toast("🚨 Alerta enviado!", icon="🚨")
                        time.sleep(2); st.session_state.panico_mode = False; st.rerun()
                    if st.form_submit_button("Cancelar"): st.session_state.panico_mode = False; st.rerun()
            
            st.markdown("---")
            with st.form("form_oc", clear_on_submit=True):
                st.subheader("Registro de Fatos")
                turma = st.selectbox("Turma", ["6A","6B","7A","7B","8A","8B","9A","9B"])
                # CORREÇÃO: Input aceita virgulas e quebras de linha
                alunos_texto = st.text_area("Alunos (separe por vírgula ou Enter)", placeholder="Ex: João Silva, Maria Souza")
                descricao = st.text_area("Descrição do Ocorrido", height=150)
                
                if st.form_submit_button("Enviar Ocorrência"):
                    if alunos_texto and descricao:
                        # Lógica robusta de separação
                        raw_names = alunos_texto.replace("\n", ",").replace(";", ",")
                        lista_alunos = [n.strip() for n in raw_names.split(",") if n.strip()]
                        
                        st.toast("✅ Enviado! Processando...", icon="🚀")
                        g, a = consultar_ia(descricao, turma)
                        salvar_ocorrencia(lista_alunos, turma, st.session_state.prof_nome, descricao, a)
                    else: st.warning("Preencha os campos.")

        with tab_hist:
            df = carregar_ocorrencias_cache()
            if not df.empty:
                meus = df[df['Professor'] == st.session_state.prof_nome]
                for i, row in meus.iloc[::-1].iterrows():
                    icon = "⏳" if row['Status_Gestao'] == "Pendente" else "✅"
                    with st.expander(f"{icon} {row['Data']} - {row['Aluno']}"):
                        st.write(f"**Fato:** {row['Descricao']}")
                        st.info(f"**IA:** {row.get('Acao_Sugerida')}")
                        if row['Status_Gestao'] == "Arquivado":
                            st.success(f"**Gestão:** {row.get('Intervencao', '')}")

# ================= GESTÃO =================
elif menu == "Painel Gestão":
    # 1. CONTROLE DE NOTIFICAÇÃO E REFRESH
    # Guardamos quantos registros existiam antes
    if 'total_ocorrencias' not in st.session_state: st.session_state.total_ocorrencias = 0
    
    st_autorefresh(interval=15000, key="gestaorefresh")

    # Verifica novos dados
    df_oc = carregar_ocorrencias_cache()
    qtd_atual = len(df_oc)
    
    # Se aumentou o número de ocorrências, avisa!
    if qtd_atual > st.session_state.total_ocorrencias:
        tocar_som("normal") # Toca som para qualquer novidade
        st.toast("🔔 Nova Ocorrência Recebida!", icon="📢")
        st.session_state.total_ocorrencias = qtd_atual

    # 2. ALERTAS DE PÂNICO
    df_alertas = carregar_alertas()
    if not df_alertas.empty:
        pendentes = df_alertas[df_alertas['Status'].isin(["Pendente", "Em Atendimento"])]
        for i, row in pendentes.iterrows():
            st.error(f"🚨 URGENTE: Sala {row['Turma']} ({row['Professor']})")
            if row['Status'] == "Pendente": tocar_som("normal") # Som extra para pânico
            
            c1, c2 = st.columns(2)
            if row['Status'] == "Pendente":
                if c1.button("👀 A Caminho", key=f"v{i}"): atualizar_alerta_status(row['Turma'], "Em Atendimento"); st.rerun()
            else:
                if c1.button("✅ Resolvido", key=f"k{i}"): atualizar_alerta_status(row['Turma'], "Resolvido"); st.rerun()
                if c2.button("📝 Registrar", key=f"r{i}"):
                    st.session_state.dados_panico = {"turma": row['Turma'], "prof": row['Professor']}
                    st.session_state.aba_ativa_gestao = "reg"
                    st.rerun()

    # 3. INTERFACE GESTÃO
    tab1, tab2, tab3, tab4 = st.tabs(["🔥 Tempo Real", "📝 Registrar", "🏫 Histórico", "⚙️ Admin"])
    
    with tab1:
        # Se houver dados de impressão, mostra o botão
        if st.session_state.dados_impressao:
            st.markdown("---")
            st.success("Intervenção Registrada!")
            
            dados_imp = st.session_state.dados_impressao
            
            # HTML bonito para impressão
            html_impressao = f"""
            <div class="area-impressao">
                <div class="card-impressao">
                    <h1 style="text-align:center;">Ocorrência Digital - Ficha de Registro</h1>
                    <hr>
                    <p><b>Data:</b> {dados_imp['data']}</p>
                    <p><b>Aluno:</b> {dados_imp['aluno']} | <b>Turma:</b> {dados_imp['turma']}</p>
                    <p><b>Professor:</b> {dados_imp['prof']}</p>
                    <hr>
                    <h3>Descrição do Fato</h3>
                    <p>{dados_imp['fato']}</p>
                    <hr>
                    <h3>Intervenção da Gestão</h3>
                    <p>{dados_imp['intervencao']}</p>
                    <hr>
                    <br><br>
                    <div style="display:flex; justify-content:space-between;">
                        <span>__________________________<br>Professor(a)</span>
                        <span>__________________________<br>Gestão</span>
                    </div>
                </div>
            </div>
            """
            
            # Mostra o preview (invisível na tela normal, visível na impressão)
            st.markdown(html_impressao, unsafe_allow_html=True)
            
            col_print1, col_print2 = st.columns(2)
            col_print1.info("👆 Pressione Ctrl+P para imprimir esta ficha.")
            if col_print2.button("Fechar / Concluir"):
                st.session_state.dados_impressao = None
                st.rerun()
            st.markdown("---")

        if not df_oc.empty and 'Status_Gestao' in df_oc.columns:
            pend = df_oc[df_oc['Status_Gestao'] != "Arquivado"]
            if pend.empty: st.success("Sem pendências.")
            
            for idx, row in pend.iloc[::-1].iterrows():
                cor, borda = "#fff3cd", "orange"
                sugestao = str(row.get('Acao_Sugerida', ''))
                if "Alta" in sugestao: cor, borda = "#ffe6e6", "red"
                elif "Baixa" in sugestao: cor, borda = "#e6fffa", "green"

                with st.container():
                    st.markdown(f"""
                    <div style='background-color:{cor}; padding:15px; border-left: 5px solid {borda}; border-radius:5px; margin-bottom:10px'>
                        <b>{row['Aluno']}</b> ({row['Turma']}) - {row['Data']}<br>
                        <i>"{row['Descricao']}"</i><br>
                        <small><b>IA:</b> {sugestao}</small>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    c1, c2, c3 = st.columns([1,3,1])
                    if c1.button("✅ Visto", key=f"ok{idx}"): 
                        atualizar_status_gestao(row['Aluno'], row['Data'], "Arquivado", "Visto")
                        st.rerun()
                    
                    with c2.popover("✍️ Intervenção"):
                        txt = st.text_area("Ação", key=f"tx{idx}")
                        if st.button("Salvar e Imprimir", key=f"sv{idx}"): 
                            atualizar_status_gestao(row['Aluno'], row['Data'], "Arquivado", txt)
                            # Prepara dados para impressão
                            st.session_state.dados_impressao = {
                                "data": row['Data'], "aluno": row['Aluno'], "turma": row['Turma'],
                                "prof": row['Professor'], "fato": row['Descricao'], "intervencao": txt
                            }
                            st.rerun()
                            
                    if c3.button("🗑️", key=f"d{idx}"): 
                        excluir_ocorrencia(row['Aluno'], row['Descricao'][:10]); st.rerun()

    with tab2: # Registrar Direto
        tg = st.selectbox("Turma", ["6A","6B","7A","7B","8A","8B","9A","9B"])
        with st.form("form_gestao_direto", clear_on_submit=True):
            ag = st.text_input("Nome do Aluno")
            dg = st.text_area("Fato Ocorrido")
            ig = st.text_area("Intervenção Realizada")
            if st.form_submit_button("Registrar Caso"):
                g, a = consultar_ia(dg, tg)
                salvar_ocorrencia([ag], tg, "GESTÃO", dg, a, ig)
                st.toast("Registro Salvo!"); time.sleep(2); st.rerun()

    with tab3:
        if not df_oc.empty:
            t = st.selectbox("Filtrar Turma:", sorted(df_oc['Turma'].astype(str).unique()))
            st.dataframe(df_oc[df_oc['Turma'] == t])
            
    with tab4:
        with st.form("np"):
            n = st.text_input("Nome"); c = st.text_input("Senha")
            if st.form_submit_button("Cadastrar"):
                conectar().worksheet("Professores").append_row([n, c]); st.success("Ok")
