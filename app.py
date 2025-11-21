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
st.set_page_config(page_title="CONVIVA - Sistema Escolar", layout="wide", page_icon="🏫")
hide_menu = """<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>"""
st.markdown(hide_menu, unsafe_allow_html=True)

# --- SONS DE ALERTA (HTML/JS) ---
def tocar_som(tipo="normal"):
    sound_url = "https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3" # Ping
    if tipo == "grave":
        sound_url = "https://assets.mixkit.co/active_storage/sfx/995/995-preview.mp3" # Alarme
    
    # Injeta audio autoplay invisível
    st.markdown(f"""
        <audio autoplay>
            <source src="{sound_url}" type="audio/mp3">
        </audio>
    """, unsafe_allow_html=True)

# --- CONEXÃO (CACHE) ---
@st.cache_resource
def conectar():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(st.secrets["service_account_info"]), scope)
    client = gspread.authorize(creds)
    return client.open("Dados_Escolares")

# --- AUTO-DETECÇÃO DE IA ---
@st.cache_resource
def configurar_ia_automatica():
    try:
        genai.configure(api_key=st.secrets["gemini_key"])
        todos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # Prioridade: Flash (Rápido/Gratuito) -> Pro -> Qualquer um
        escolhido = next((m for m in todos if "flash" in m and "1.5" in m), None)
        if not escolhido: escolhido = next((m for m in todos if "flash" in m), None)
        if not escolhido: escolhido = next((m for m in todos if "gemini" in m), todos[0] if todos else None)
            
        return escolhido
    except: return None

nome_modelo_ativo = configurar_ia_automatica()

# --- FUNÇÕES DE DADOS ---
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
        # Salva uma linha para cada aluno
        for aluno in alunos_lista:
            # Remove espaços extras
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

# --- IA (PROTOCOLOS SP - CONVIVA) ---
def consultar_ia(descricao, turma):
    if not nome_modelo_ativo: return "Erro Config", "IA Indisponível"
    
    # PROMPT ESPECIALIZADO PARA SP/CONVIVA
    prompt = f"""
    Você é um especialista do programa CONVIVA SP (Rede Estadual de São Paulo).
    Analise a ocorrência escolar abaixo baseando-se estritamente no Protocolo 179 e normas de convivência.
    
    Dados: Turma {turma} | Fato: "{descricao}"
    
    Classifique a GRAVIDADE em:
    - ALTA (Violência física, armas, drogas, bullying severo, autolesão)
    - MÉDIA (Conflitos verbais, indisciplina recorrente, matar aula)
    - BAIXA (Conversa paralela, celular, atraso)

    Sugira AÇÃO (curta e direta) focada na mediação, acolhimento e regimento escolar.
    
    Responda APENAS no formato:
    GRAVIDADE: [Alta/Média/Baixa]
    AÇÃO: [Sua sugestão]
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
    except: return "Média", "Erro na análise automática. Verificar manualmente."

# --- GESTÃO DE LOGIN (PERSISTENTE VIA URL) ---
# Verifica se há parametros na URL
params = st.query_params
if "prof_logado" in params:
    st.session_state.prof_logado = True
    st.session_state.prof_nome = params["prof_nome"]

if 'prof_logado' not in st.session_state: st.session_state.prof_logado = False
if 'prof_nome' not in st.session_state: st.session_state.prof_nome = ""
if 'panico_mode' not in st.session_state: st.session_state.panico_mode = False

# --- INTERFACE ---
st.title("🏫 CONVIVA - Sistema Escolar")
menu = st.sidebar.radio("Menu", ["Acesso Professor", "Painel Gestão"])

# ==========================================
# ÁREA DO PROFESSOR
# ==========================================
if menu == "Acesso Professor":
    
    if not st.session_state.prof_logado:
        # FORMULÁRIO DE LOGIN (Permite Enter)
        with st.form("login_form"):
            st.write("### 🔐 Acesso Restrito")
            ln = st.text_input("Nome")
            lc = st.text_input("Código", type="password")
            submitted = st.form_submit_button("Entrar no Sistema")
            
            if submitted:
                df = carregar_professores()
                if not df.empty:
                    df['Codigo'] = df['Codigo'].astype(str)
                    if not df[(df['Nome'] == ln) & (df['Codigo'] == lc)].empty:
                        st.session_state.prof_logado = True
                        st.session_state.prof_nome = ln
                        # Salva na URL para persistir no F5
                        st.query_params["prof_logado"] = "true"
                        st.query_params["prof_nome"] = ln
                        st.rerun()
                    else: st.error("Dados inválidos.")
    else:
        # HEADER PROFESSOR
        col_head1, col_head2 = st.columns([4,1])
        col_head1.success(f"👤 Olá, **{st.session_state.prof_nome}**")
        if col_head2.button("Sair"):
            st.session_state.prof_logado = False
            st.query_params.clear() # Limpa URL
            st.rerun()

        # ABAS DO PROFESSOR
        tab_reg, tab_hist = st.tabs(["📝 Nova Ocorrência", "🗂️ Meus Registros"])

        with tab_reg:
            # BOTÃO DE PÂNICO
            c1, c2 = st.columns([3,1])
            c1.warning("⚠️ Utilize o botão ao lado apenas para **Emergências Graves** que precisem da presença imediata da direção.")
            if c2.button("🚨 CHAMAR GESTÃO", type="primary"): st.session_state.panico_mode = True
            
            if st.session_state.panico_mode:
                with st.form("panico_form"):
                    st.error("CONFIRMAR CHAMADO DE EMERGÊNCIA?")
                    t = st.selectbox("Sua Sala Atual:", ["6A","6B","7A","7B","8A","8B","9A","9B"])
                    confirmar = st.form_submit_button("CONFIRMAR")
                    cancelar = st.form_submit_button("Cancelar")
                    
                    if confirmar:
                        salvar_alerta(t, st.session_state.prof_nome)
                        st.toast("🚨 Alerta enviado! A gestão está a caminho.", icon="🚨")
                        time.sleep(2)
                        st.session_state.panico_mode = False; st.rerun()
                    if cancelar: st.session_state.panico_mode = False; st.rerun()
            
            st.markdown("---")
            
            # FORMULÁRIO DE OCORRÊNCIA (LIMPA SOZINHO COM CLEAR_ON_SUBMIT)
            with st.form("ocorrencia_form", clear_on_submit=True):
                st.subheader("Registro de Fatos")
                
                turma = st.selectbox("Turma", ["6A","6B","7A","7B","8A","8B","9A","9B"])
                
                # CAMPO DE ALUNOS MELHORADO (Texto livre)
                alunos_texto = st.text_area("Alunos Envolvidos", placeholder="Digite os nomes. Pode separar por vírgula ou um por linha.\nEx: João Silva, Maria Souza")
                
                descricao = st.text_area("Descrição do Ocorrido", height=150)
                
                # Botão de Envio
                enviar = st.form_submit_button("Enviar Ocorrência")
                
                if enviar:
                    if alunos_texto and descricao:
                        # Processa lista de nomes (quebra por virgula ou enter)
                        lista_alunos = [nome.strip() for nome in alunos_texto.replace("\n", ",").split(",") if nome.strip()]
                        
                        # Feedback imediato visual
                        st.toast("✅ Enviado! Processando inteligência...", icon="🚀")
                        
                        # Processamento IA e Salvamento (Invisível para o form que já limpou)
                        grav, acao = consultar_ia(descricao, turma)
                        salvar_ocorrencia(lista_alunos, turma, st.session_state.prof_nome, descricao, acao)
                        
                    else:
                        st.warning("Preencha os alunos e a descrição.")

        with tab_hist:
            st.subheader("Histórico de Registros")
            df = carregar_ocorrencias_cache()
            if not df.empty:
                # Filtra apenas ocorrencias deste professor
                meus_regs = df[df['Professor'] == st.session_state.prof_nome]
                
                if not meus_regs.empty:
                    for i, row in meus_regs.iloc[::-1].iterrows():
                        # Status Visual
                        status_icon = "⏳" if row['Status_Gestao'] == "Pendente" else "✅"
                        cor_border = "orange" if row['Status_Gestao'] == "Pendente" else "green"
                        
                        intervencao_texto = row.get('Intervencao', '')
                        if not intervencao_texto: intervencao_texto = "Aguardando análise..."
                        
                        with st.expander(f"{status_icon} {row['Data']} - {row['Aluno']} ({row['Turma']})"):
                            st.write(f"**Ocorrência:** {row['Descricao']}")
                            st.info(f"**Classificação IA:** {row.get('Acao_Sugerida')}")
                            
                            st.write("---")
                            if row['Status_Gestao'] == "Arquivado":
                                st.success(f"**Retorno da Gestão:** {intervencao_texto}")
                            else:
                                st.warning("**Status:** Em análise pela gestão.")
                else:
                    st.info("Você ainda não registrou ocorrências.")

# ==========================================
# ÁREA DA GESTÃO
# ==========================================
elif menu == "Painel Gestão":
    # Refresh automático (15s) para pegar alertas de pânico
    count = st_autorefresh(interval=15000, key="gestaorefresh")

    # 1. VERIFICAÇÃO DE ALERTAS (PÂNICO)
    df_alertas = carregar_alertas()
    alerta_sonoro = False
    
    if not df_alertas.empty:
        pendentes = df_alertas[df_alertas['Status'].isin(["Pendente", "Em Atendimento"])]
        for i, row in pendentes.iterrows():
            st.error(f"🚨 URGENTE: Sala {row['Turma']} ({row['Professor']})")
            # Som de alarme se for pendente
            if row['Status'] == "Pendente":
                alerta_sonoro = True
                
            c1, c2 = st.columns(2)
            if row['Status'] == "Pendente":
                if c1.button("👀 A Caminho", key=f"v{i}"): atualizar_alerta_status(row['Turma'], "Em Atendimento"); st.rerun()
            else:
                if c1.button("✅ Resolvido", key=f"k{i}"): atualizar_alerta_status(row['Turma'], "Resolvido"); st.rerun()
                if c2.button("📝 Registrar", key=f"r{i}"):
                    st.session_state.dados_panico = {"turma": row['Turma'], "prof": row['Professor']}
                    st.session_state.aba_ativa_gestao = "reg"
                    st.rerun()

    # 2. VERIFICAÇÃO DE OCORRÊNCIAS GRAVES (NOVAS)
    df_oc = carregar_ocorrencias_cache()
    tem_grave_pendente = False
    if not df_oc.empty and 'Status_Gestao' in df_oc.columns:
        # Procura ocorrências pendentes que a IA marcou como Alta
        graves = df_oc[(df_oc['Status_Gestao'] != "Arquivado") & (df_oc['Acao_Sugerida'].str.contains("Alta", na=False))]
        if not graves.empty:
            tem_grave_pendente = True

    # LÓGICA DO SOM
    if alerta_sonoro:
        tocar_som("grave")
    elif tem_grave_pendente:
        # Toca som apenas 1 vez a cada refresh se houver grave, para não enlouquecer
        tocar_som("grave")

    # --- INTERFACE GESTÃO ---
    tab1, tab2, tab3, tab4 = st.tabs(["🔥 Tempo Real", "📝 Registrar", "🏫 Histórico", "⚙️ Admin"])
    
    with tab1:
        if not df_oc.empty and 'Status_Gestao' in df_oc.columns:
            pend = df_oc[df_oc['Status_Gestao'] != "Arquivado"]
            if pend.empty: st.success("Sem pendências.")
            
            for idx, row in pend.iloc[::-1].iterrows():
                # Cores e Icones baseados na IA
                sugestao = str(row.get('Acao_Sugerida', ''))
                
                cor_fundo = "#fff3cd" # Amarelo
                borda = "orange"
                
                if "Alta" in sugestao: 
                    cor_fundo = "#ffe6e6" # Vermelho claro
                    borda = "red"
                    st.markdown(f"### 🔴 GRAVIDADE ALTA DETECTADA")
                elif "Baixa" in sugestao:
                    cor_fundo = "#e6fffa" # Verde claro
                    borda = "green"
                elif "Erro" in sugestao:
                    cor_fundo = "#f0f0f0"
                    borda = "gray"

                with st.container():
                    st.markdown(f"""
                    <div style='background-color:{cor_fundo}; padding:15px; border-left: 5px solid {borda}; border-radius:5px; margin-bottom:10px'>
                        <div style="display:flex; justify-content:space-between;">
                            <span><b>{row['Aluno']}</b> ({row['Turma']})</span>
                            <small>{row['Data']}</small>
                        </div>
                        <p style="margin-top:5px"><i>"{row['Descricao']}"</i></p>
                        <hr style="margin:5px 0; opacity:0.2">
                        <small><b>🤖 CONVIVA/IA:</b> {sugestao}</small>
                        <br><small>Prof: {row['Professor']}</small>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    c1, c2, c3 = st.columns([1,3,1])
                    
                    # Botão OK
                    if c1.button("✅ Visto", key=f"ok{idx}"): 
                        atualizar_status_gestao(row['Aluno'], row['Data'], "Arquivado", "Visto pela gestão (sem intervenção registrada)")
                        st.rerun()
                    
                    # Botão Intervenção
                    with c2.popover("✍️ Registrar Intervenção"):
                        st.write(f"Aluno: {row['Aluno']}")
                        txt = st.text_area("Qual medida foi tomada?", key=f"tx{idx}", placeholder="Ex: Conversa com aluno, chamada aos pais (Prot. 179)...")
                        if st.button("Salvar e Arquivar", key=f"sv{idx}"): 
                            atualizar_status_gestao(row['Aluno'], row['Data'], "Arquivado", txt)
                            st.success("Registrado!")
                            time.sleep(1)
                            st.rerun()
                            
                    # Botão Excluir
                    if c3.button("🗑️", key=f"d{idx}"): 
                        excluir_ocorrencia(row['Aluno'], row['Descricao'][:10])
                        st.rerun()

    with tab2: # Registrar Direto
        dpre = st.session_state.get('dados_panico', {})
        turma_ini = dpre.get('turma', "6A")
        if dpre: st.info(f"Resolvendo chamado da {turma_ini}")
        
        tg = st.selectbox("Turma", ["6A","6B","7A","7B","8A","8B","9A","9B"], index=["6A","6B","7A","7B","8A","8B","9A","9B"].index(turma_ini) if turma_ini in ["6A","6B","7A","7B","8A","8B","9A","9B"] else 0)
        
        with st.form("form_gestao_direto", clear_on_submit=True):
            ag = st.text_input("Nome do Aluno")
            dg = st.text_area("Fato Ocorrido")
            ig = st.text_area("Intervenção Realizada")
            btn_reg = st.form_submit_button("Registrar Caso")
            
            if btn_reg:
                g, a = consultar_ia(dg, tg)
                salvar_ocorrencia([ag], tg, "GESTÃO", dg, a, ig)
                if dpre: atualizar_alerta_status(turma_ini, "Resolvido"); del st.session_state['dados_panico']
                st.toast("Registro Salvo com Sucesso!")
                time.sleep(2); st.rerun()

    with tab3:
        df = carregar_ocorrencias_cache()
        if not df.empty:
            t = st.selectbox("Filtrar Turma:", sorted(df['Turma'].astype(str).unique()))
            st.dataframe(df[df['Turma'] == t])
            
    with tab4:
        with st.form("np"):
            n = st.text_input("Nome")
            c = st.text_input("Senha")
            if st.form_submit_button("Cadastrar Prof"):
                conectar().worksheet("Professores").append_row([n, c])
                st.success("Ok")
