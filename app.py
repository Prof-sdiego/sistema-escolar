import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
import time
from streamlit_autorefresh import st_autorefresh
import google.generativeai as genai
from fpdf import FPDF
import hashlib
import urllib.parse
import plotly.express as px

# --- CONFIGURAÇÕES GERAIS ---
st.set_page_config(page_title="EduGestor Pro", layout="wide", page_icon="🎓")

# ==============================================================================
#  🎨 CSS PERSONALIZADO (VISUAL EDUGESTOR)
# ==============================================================================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background-color: #F3F4F6; }
    #MainMenu {visibility: hidden;} 
    footer {visibility: hidden;} 
    header {visibility: hidden;}
    
    section[data-testid="stSidebar"] { background-color: #FFFFFF; border-right: 1px solid #E5E7EB; }
    
    .card {
        background-color: white; border-radius: 12px; padding: 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); margin-bottom: 20px; border: 1px solid #F3F4F6;
    }
    .metric-container { display: flex; justify-content: space-between; align-items: center; }
    .metric-label { font-size: 0.9rem; color: #6B7280; font-weight: 600; }
    .metric-value { font-size: 1.8rem; font-weight: 700; color: #111827; }
    .metric-icon {
        width: 40px; height: 40px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 1.2rem;
    }
    .icon-blue { background-color: #DBEAFE; color: #2563EB; }
    .icon-red { background-color: #FEE2E2; color: #DC2626; }
    .icon-purple { background-color: #EDE9FE; color: #7C3AED; }

    .ai-card {
        background: linear-gradient(135deg, #6366F1 0%, #4F46E5 100%);
        border-radius: 16px; padding: 25px; color: white; margin-bottom: 20px;
        box-shadow: 0 10px 15px -3px rgba(79, 70, 229, 0.4); position: relative; overflow: hidden;
    }
    .ai-card h3 { color: white !important; margin: 0 0 10px 0; }
    .ai-card p { color: #E0E7FF; font-size: 0.9rem; }
    
    .badge { padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; }
    .badge-leve { background-color: #D1FAE5; color: #065F46; }
    .badge-media { background-color: #FEF3C7; color: #92400E; }
    .badge-grave { background-color: #FEE2E2; color: #991B1B; }

    div.stButton > button { border-radius: 8px; font-weight: 600; border: none; padding: 0.5rem 1rem; transition: all 0.2s; }
    div.stButton > button[kind="primary"] { background-color: #4F46E5; color: white; }
    div.stButton > button[kind="primary"]:hover { background-color: #4338CA; box-shadow: 0 4px 12px rgba(79, 70, 229, 0.3); }
    
    .avatar {
        width: 48px; height: 48px; border-radius: 50%; background-color: #E0E7FF; color: #4F46E5;
        display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 1.2rem; margin-right: 15px;
    }
    
    @media print {
        @page { size: A4; margin: 0; }
        body * { visibility: hidden; }
        .area-impressao, .area-impressao * { visibility: visible; }
        .area-impressao { position: absolute; left: 0; top: 0; width: 100%; }
    }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
#  LÓGICA (BACKEND)
# ==============================================================================

# --- SEGURANÇA ---
def verificar_senha_mestra(senha_digitada):
    hash_real = "0b3ea097e02015db007c4b357e12692702b2226633299d0775907ff424a06e30" # Master2025
    return hashlib.sha256(senha_digitada.encode()).hexdigest() == hash_real

# --- CONEXÃO ---
@st.cache_resource
def conectar():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(st.secrets["service_account_info"]), scope)
    client = gspread.authorize(creds)
    return client.open("Dados_Escolares")

# --- IA ---
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

# --- CARREGAMENTO DE DADOS ---
def carregar_alertas(): 
    try:
        d = conectar().worksheet("Alertas").get_all_records()
        return pd.DataFrame(d) if d else pd.DataFrame(columns=["Data", "Turma", "Professor", "Status"])
    except: return pd.DataFrame(columns=["Data", "Turma", "Professor", "Status"])

@st.cache_data(ttl=60) 
def carregar_ocorrencias_cache(): 
    try:
        d = conectar().sheet1.get_all_records()
        return pd.DataFrame(d) if d else pd.DataFrame(columns=["Data", "Aluno", "Turma", "Professor", "Descricao", "Acao_Sugerida", "Intervencao", "Status_Gestao"])
    except: return pd.DataFrame()

@st.cache_data(ttl=3600)
def carregar_professores(): 
    try:
        d = conectar().worksheet("Professores").get_all_records()
        return pd.DataFrame(d)
    except: return pd.DataFrame()

@st.cache_data(ttl=3600)
def carregar_gestores(): 
    try:
        d = conectar().worksheet("Gestores").get_all_records()
        return pd.DataFrame(d)
    except: return pd.DataFrame()

@st.cache_data(ttl=3600)
def carregar_alunos_contatos(): 
    try:
        d = conectar().worksheet("Alunos").get_all_records()
        return pd.DataFrame(d)
    except: return pd.DataFrame(columns=["Nome", "Turma", "Responsavel", "Telefone"])

# --- SALVAMENTO ---
def limpar_cache(): st.cache_data.clear()

def salvar_ocorrencia(alunos_lista, turma, prof, desc, acao, intervencao=""):
    try:
        sheet = conectar().sheet1
        data = datetime.now().strftime("%Y-%m-%d %H:%M")
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

def cadastrar_usuario(tipo, nome, codigo):
    try:
        aba = "Professores" if tipo == "Professor" else "Gestores"
        conectar().worksheet(aba).append_row([nome, codigo])
        limpar_cache(); return True
    except: return False

# --- SOM ---
def gerenciar_som(tipo="normal", chave_evento=None):
    if 'sons_tocados' not in st.session_state: st.session_state.sons_tocados = set()
    if chave_evento in st.session_state.sons_tocados: return
    sound_url = "https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"
    if tipo == "grave": sound_url = "https://assets.mixkit.co/active_storage/sfx/995/995-preview.mp3"
    st.markdown(f"""<audio autoplay><source src="{sound_url}" type="audio/mp3"></audio>""", unsafe_allow_html=True)
    if chave_evento: st.session_state.sons_tocados.add(chave_evento)

# --- TRANSCRIÇÃO ---
def transcrever_audio(audio_bytes):
    if not nome_modelo_ativo: return ""
    try:
        modelo = genai.GenerativeModel(nome_modelo_ativo)
        resp = modelo.generate_content(["Transcreva fielmente.", {"mime_type": "audio/mp3", "data": audio_bytes}])
        return resp.text
    except: return ""

# --- IA FUNÇÕES ---
def consultar_ia(descricao, turma):
    if not nome_modelo_ativo: return "Erro Config", "IA Indisponível"
    prompt = f"""Especialista CONVIVA SP (Protocolo 179). Dados: Turma {turma} | Fato: "{descricao}". Classifique GRAVIDADE: ALTA, MÉDIA, BAIXA. Sugira AÇÃO mediação. Responda: GRAVIDADE: [G] AÇÃO: [A]"""
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

def gerar_mensagem_whats(aluno, responsavel, fato, intervencao):
    if not nome_modelo_ativo: return f"Olá {responsavel}, informamos sobre o aluno {aluno}. Motivo: {fato}"
    prompt = f"""Escreva msg curta WhatsApp para {responsavel}, responsável aluno {aluno}. Contexto: Escola informa ocorrência: "{fato}". Ação: "{intervencao}". Tom: Acolhedor, parceiro. Max 3 linhas."""
    try:
        modelo = genai.GenerativeModel(nome_modelo_ativo)
        resp = modelo.generate_content(prompt)
        return resp.text
    except: return f"Olá {responsavel}, sobre aluno {aluno}: {fato}."

# --- PDF (Design Limpo) ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 16); self.cell(0, 10, 'EDUGESTOR - RELATÓRIO', 0, 1, 'C'); self.ln(5); self.line(10, 25, 200, 25)
    def footer(self):
        self.set_y(-15); self.set_font('Arial', 'I', 8); self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def desenhar_pagina_ocorrencia(pdf, dados):
    def limpa(t): return str(t).encode('latin-1', 'replace').decode('latin-1')
    pdf.set_font("Arial", size=12)
    # Cabeçalho Dados
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, limpa(f"REGISTRO DE OCORRÊNCIA - {dados['Data']}"), 0, 1, 'L', True); pdf.ln(5)
    
    pdf.set_font("Arial", 'B', 11); pdf.cell(25, 8, "Aluno:", 0, 0); pdf.set_font("Arial", '', 11); pdf.cell(80, 8, limpa(dados['Aluno']), 0, 0)
    pdf.set_font("Arial", 'B', 11); pdf.cell(20, 8, "Turma:", 0, 0); pdf.set_font("Arial", '', 11); pdf.cell(0, 8, limpa(dados['Turma']), 0, 1)
    pdf.set_font("Arial", 'B', 11); pdf.cell(25, 8, "Prof:", 0, 0); pdf.set_font("Arial", '', 11); pdf.cell(0, 8, limpa(dados['Professor']), 0, 1)
    pdf.line(10, pdf.get_y()+5, 200, pdf.get_y()+5); pdf.ln(10)
    
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, limpa("DESCRIÇÃO:"), 0, 1)
    pdf.set_font("Arial", '', 11); pdf.multi_cell(0, 6, limpa(dados['Descricao'])); pdf.ln(8)
    
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, limpa("INTERVENÇÃO / ENCAMINHAMENTO:"), 0, 1)
    pdf.set_font("Arial", '', 11); pdf.multi_cell(0, 6, limpa(dados.get('Intervencao', '') or "Sem registro."))
    
    pdf.set_y(-50); y = pdf.get_y(); pdf.set_font("Arial", '', 9)
    pdf.line(20, y, 90, y); pdf.text(40, y+5, limpa("Aluno(a)"))
    pdf.line(120, y, 190, y); pdf.text(140, y+5, limpa("Responsável"))
    pdf.line(70, y+25, 140, y+25); pdf.text(90, y+30, limpa("Gestão Escolar"))

def gerar_pdf_lote(dataframe_filtrado):
    pdf = PDF()
    for index, row in dataframe_filtrado.iterrows(): pdf.add_page(); desenhar_pagina_ocorrencia(pdf, row.to_dict())
    return pdf.output(dest='S').encode('latin-1')

# --- ESTADOS DA SESSÃO ---
if 'panico_mode' not in st.session_state: st.session_state.panico_mode = False
if 'id_intervencao_ativa' not in st.session_state: st.session_state.id_intervencao_ativa = None
if 'total_ocorrencias' not in st.session_state: st.session_state.total_ocorrencias = 0
if 'pdf_buffer' not in st.session_state: st.session_state.pdf_buffer = None
if 'prof_turmas_permitidas' not in st.session_state: st.session_state.prof_turmas_permitidas = []

# Recuperação de Login (Session)
params = st.query_params
if "prof_logado" in params: 
    st.session_state.prof_logado = True; st.session_state.prof_nome = params["prof_nome"]
if 'prof_logado' not in st.session_state: st.session_state.prof_logado = False

if "gestao_logada" in params: st.session_state.gestao_logada = True; st.session_state.gestao_nome = params["gestao_nome"]
if 'gestao_logada' not in st.session_state: st.session_state.gestao_logada = False

# ==============================================================================
#  LAYOUT DO MENU LATERAL
# ==============================================================================
with st.sidebar:
    st.markdown("## 🎓 **EduGestor**")
    st.markdown('<div style="height: 2px; background-color: #E5E7EB; margin-bottom: 20px;"></div>', unsafe_allow_html=True)
    
    menu = st.radio("", ["Acesso Professor", "Painel Gestão"], index=0, key="main_menu")
    
    st.markdown("---")
    if st.session_state.prof_logado:
        st.write(f"👤 **{st.session_state.prof_nome}**")
        st.caption("Professor(a)")
    elif st.session_state.gestao_logada:
        st.write(f"📊 **{st.session_state.gestao_nome}**")
        st.caption("Coordenação")
    
    st.markdown("<br><br><small style='color:gray'>v2.0 AI Powered</small>", unsafe_allow_html=True)

# ==============================================================================
#  ÁREA DO PROFESSOR
# ==============================================================================
if menu == "Acesso Professor":
    
    if not st.session_state.prof_logado:
        c1, c2, c3 = st.columns([1,2,1])
        with c2:
            st.markdown("<br><br><br>", unsafe_allow_html=True)
            st.markdown("### 👋 Bem-vindo, Professor(a)")
            with st.form("login_prof"):
                ln = st.text_input("Seu Nome"); lc = st.text_input("Código de Acesso", type="password")
                if st.form_submit_button("Entrar no Sistema", type="primary"):
                    df = carregar_professores()
                    if not df.empty:
                        df['Codigo'] = df['Codigo'].astype(str)
                        usuario = df[(df['Nome'] == ln) & (df['Codigo'] == lc)]
                        if not usuario.empty:
                            st.session_state.prof_logado = True; st.session_state.prof_nome = ln
                            
                            # --- CORREÇÃO: CARREGA TURMAS AO LOGAR ---
                            turmas_raw = str(usuario.iloc[0].get('Turmas', '')).strip()
                            if turmas_raw: st.session_state.prof_turmas_permitidas = [t.strip() for t in turmas_raw.split(",") if t.strip()]
                            else: st.session_state.prof_turmas_permitidas = ["6A","6B","7A","7B","8A","8B","9A","9B"]
                            
                            st.query_params["prof_logado"] = "true"; st.query_params["prof_nome"] = ln; st.rerun()
                        else: st.error("Dados inválidos.")
                    else: st.error("Erro ao conectar com a escola.")
    
    else:
        # --- CORREÇÃO: SE RECUPERAR SESSÃO E LISTA TIVER VAZIA ---
        if not st.session_state.prof_turmas_permitidas:
             st.session_state.prof_turmas_permitidas = ["6A","6B","7A","7B","8A","8B","9A","9B"]

        # HEADER
        c_head1, c_head2 = st.columns([5,1])
        with c_head1: st.markdown(f"## Olá, **{st.session_state.prof_nome}**")
        with c_head2: 
            if st.button("Sair", key="sair_p"): st.session_state.prof_logado = False; st.query_params.clear(); st.rerun()

        # TABS
        tab_reg, tab_hist = st.tabs(["📝 Registrar Ocorrência", "🗂️ Meus Registros"])

        with tab_reg:
            with st.expander("🚨 CHAMAR GESTÃO (Clique aqui apenas em caso grave)"):
                st.warning("Isso enviará um alerta vermelho para a sala da direção.")
                if st.button("CHAMAR AJUDA AGORA", type="primary"):
                    salvar_alerta("Sala Indefinida (Ver Prof)", st.session_state.prof_nome)
                    st.toast("Alerta enviado!", icon="🚨")

            st.markdown('<div class="card">', unsafe_allow_html=True)
            
            # INPUT POR VOZ
            st.write("🎙️ **Ditado Inteligente:**")
            audio_val = st.audio_input("Grave a ocorrência")
            texto_transcrito = ""
            if audio_val:
                with st.spinner("Transcrevendo..."):
                    texto_transcrito = transcrever_audio(audio_val.read())
                    if texto_transcrito: st.success("Áudio convertido!")

            with st.form("form_oc", clear_on_submit=True):
                st.markdown("#### Nova Ocorrência")
                turma = st.selectbox("Turma", st.session_state.prof_turmas_permitidas)
                
                # LISTA DE ALUNOS INTELIGENTE
                df_alunos = carregar_alunos_contatos()
                lista_alunos_turma = []
                if not df_alunos.empty and 'Turma' in df_alunos.columns:
                    lista_alunos_turma = sorted(df_alunos[df_alunos['Turma'] == turma]['Nome'].unique().tolist())
                
                if lista_alunos_turma:
                    alunos_sel = st.multiselect("Selecione os Alunos:", lista_alunos_turma)
                    alunos_texto = ""
                else:
                    alunos_texto = st.text_area("Alunos (separados por vírgula)", placeholder="Ex: João, Maria")
                    alunos_sel = []

                descricao = st.text_area("Descrição Detalhada do Fato", value=texto_transcrito, height=150)
                
                if st.form_submit_button("Enviar Ocorrência", type="primary"):
                    final_alunos = alunos_sel if lista_alunos_turma else [n.strip() for n in alunos_texto.split(",") if n.strip()]
                    
                    if final_alunos and descricao:
                        st.toast("✅ Enviado! A IA está analisando...", icon="✨")
                        g, a = consultar_ia(descricao, turma)
                        salvar_ocorrencia(final_alunos, turma, st.session_state.prof_nome, descricao, a)
                    else: st.warning("Por favor, preencha todos os campos.")
            st.markdown('</div>', unsafe_allow_html=True)

        with tab_hist:
            df = carregar_ocorrencias_cache()
            if not df.empty:
                meus = df[df['Professor'] == st.session_state.prof_nome]
                if meus.empty:
                    st.info("Nenhum registro encontrado.")
                else:
                    for i, row in meus.iloc[::-1].iterrows():
                        cor_borda = "#10B981" if row['Status_Gestao'] == "Arquivado" else "#F59E0B"
                        icon_st = "✅ Resolvido" if row['Status_Gestao'] == "Arquivado" else "⏳ Em Análise"
                        st.markdown(f"""
                        <div class="card" style="border-left: 5px solid {cor_borda};">
                            <div style="display:flex; justify-content:space-between; align-items:center;">
                                <div>
                                    <span style="font-weight:bold; font-size:1.1rem;">{row['Aluno']}</span>
                                    <span style="color:gray; font-size:0.9rem;"> • {row['Turma']} • {row['Data']}</span>
                                </div>
                                <span style="background:#F3F4F6; padding:4px 8px; border-radius:6px; font-size:0.8rem;">{icon_st}</span>
                            </div>
                            <p style="margin-top:10px; color:#374151;">{row['Descricao']}</p>
                            <div style="background:#F9FAFB; padding:10px; border-radius:8px; margin-top:10px;">
                                <small style="color:#6B7280; font-weight:bold;">🤖 Análise IA:</small><br>
                                <small style="color:#4B5563;">{row.get('Acao_Sugerida')}</small>
                            </div>
                        </div>""", unsafe_allow_html=True)

# ==============================================================================
#  ÁREA DA GESTÃO
# ==============================================================================
elif menu == "Painel Gestão":
    
    if not st.session_state.gestao_logada:
        c1, c2, c3 = st.columns([1,2,1])
        with c2:
            st.markdown("<br><br>", unsafe_allow_html=True)
            st.markdown("### 📊 Portal da Coordenação")
            with st.form("login_gestao"):
                gn = st.text_input("Usuário"); gc = st.text_input("Senha", type="password")
                if st.form_submit_button("Acessar Painel", type="primary"):
                    login_ok = False
                    if verificar_senha_mestra(gc): login_ok = True
                    else:
                        df_g = carregar_gestores()
                        if not df_g.empty:
                            df_g['Codigo'] = df_g['Codigo'].astype(str)
                            if not df_g[(df_g['Nome'] == gn) & (df_g['Codigo'] == gc)].empty: login_ok = True
                    if login_ok:
                        st.session_state.gestao_logada = True; st.session_state.gestao_nome = gn
                        st.query_params["gestao_logada"] = "true"; st.query_params["gestao_nome"] = gn; st.rerun()
                    else: st.error("Acesso negado.")
    else:
        c_head1, c_head2 = st.columns([5,1])
        with c_head1: st.markdown(f"## Painel de Controle")
        with c_head2: 
            if st.button("Sair", key="sg"): st.session_state.gestao_logada = False; st.query_params.clear(); st.rerun()

        if st.session_state.id_intervencao_ativa is None: st_autorefresh(interval=15000, key="gestaorefresh")

        df_oc = carregar_ocorrencias_cache()
        df_alertas = carregar_alertas()
        
        # --- MÉTRICAS ---
        total_hoje = 0
        total_bimestre = len(df_oc)
        criticos = 0
        
        if not df_oc.empty:
            hoje = datetime.now().strftime("%Y-%m-%d")
            total_hoje = len(df_oc[df_oc['Data'].str.contains(hoje)])
            if 'Acao_Sugerida' in df_oc.columns:
                criticos = len(df_oc[df_oc['Acao_Sugerida'].str.contains("Alta", na=False)])

        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1: st.markdown(f"""<div class="card"><div class="metric-container"><div><div class="metric-label">Ocorrências Hoje</div><div class="metric-value">{total_hoje}</div></div><div class="metric-icon icon-blue">📅</div></div></div>""", unsafe_allow_html=True)
        with col_m2: st.markdown(f"""<div class="card"><div class="metric-container"><div><div class="metric-label">Casos Críticos (IA)</div><div class="metric-value">{criticos}</div></div><div class="metric-icon icon-red">⚠️</div></div></div>""", unsafe_allow_html=True)
        with col_m3: st.markdown(f"""<div class="card"><div class="metric-container"><div><div class="metric-label">Total Bimestre</div><div class="metric-value">{total_bimestre}</div></div><div class="metric-icon icon-purple">📊</div></div></div>""", unsafe_allow_html=True)

        # ALERTAS
        if not df_alertas.empty:
            pendentes = df_alertas[df_alertas['Status'].isin(["Pendente", "Em Atendimento"])]
            for i, row in pendentes.iterrows():
                st.error(f"🚨 URGENTE: Sala {row['Turma']} ({row['Professor']})")
                if row['Status'] == "Pendente": gerenciar_som("grave", f"p{row['Data']}")
                c1, c2 = st.columns(2)
                if row['Status'] == "Pendente":
                    if c1.button("👀 A Caminho", key=f"v{i}"): atualizar_alerta_status(row['Turma'], "Em Atendimento"); st.rerun()
                else:
                    if c1.button("✅ Resolvido", key=f"k{i}"): atualizar_alerta_status(row['Turma'], "Resolvido"); st.rerun()
                    if c2.button("📝 Registrar", key=f"r{i}"):
                        st.session_state.dados_panico = {"turma": row['Turma'], "prof": row['Professor']}
                        st.session_state.aba_ativa_gestao = "reg"; st.rerun()

        col_feed, col_sidebar = st.columns([2, 1])

        with col_sidebar:
            st.markdown("""<div class="ai-card"><h3>🤖 EduGestor AI</h3><p>Monitoramento em tempo real e sugestões baseadas no Protocolo 179.</p></div>""", unsafe_allow_html=True)
            tab_reg, tab_rel, tab_adm = st.tabs(["📝 Novo", "🖨️ Relatórios", "⚙️ Admin"])
            
            with tab_reg:
                with st.form("quick_reg", clear_on_submit=True):
                    tg = st.selectbox("Turma", ["6A","6B","7A","7B","8A","8B","9A","9B"])
                    ag = st.text_input("Aluno")
                    dg = st.text_area("Fato")
                    ig = st.text_area("Intervenção")
                    if st.form_submit_button("Registrar"):
                        g, a = consultar_ia(dg, tg)
                        salvar_ocorrencia([ag], tg, "GESTÃO", dg, a, ig); st.toast("Salvo!"); time.sleep(2); st.rerun()
            
            with tab_rel:
                if not df_oc.empty:
                    tr = st.radio("Tipo:", ["Aluno", "Turma"])
                    ts = st.selectbox("Turma:", sorted(df_oc['Turma'].astype(str).unique()), key="relt")
                    dft = df_oc[df_oc['Turma'] == ts]
                    if tr == "Aluno":
                        al = st.selectbox("Aluno:", sorted(dft['Aluno'].unique()))
                        if st.button("📄 Gerar PDF"):
                            pdf = gerar_pdf_lote(dft[dft['Aluno'] == al])
                            st.download_button("📥 Baixar", pdf, f"Rel_{al}.pdf", "application/pdf")
                    else:
                        if st.button(f"📄 PDF Turma ({len(dft)})"):
                            pdf = gerar_pdf_lote(dft)
                            st.download_button("📥 Baixar", pdf, f"Rel_{ts}.pdf", "application/pdf")
            
            with tab_adm:
                with st.form("n_usr"):
                    tp = st.selectbox("Tipo", ["Professor", "Gestor"])
                    nm = st.text_input("Nome")
                    cd = st.text_input("Senha")
                    if st.form_submit_button("Criar"): cadastrar_usuario(tp, nm, cd); st.success("Criado!")

        with col_feed:
            st.markdown("### 📋 Ocorrências Recentes")
            if qtd_atual := len(df_oc):
                if qtd_atual > st.session_state.total_ocorrencias:
                    gerenciar_som("normal", f"n{qtd_atual}"); st.toast("🔔 Nova Ocorrência!"); st.session_state.total_ocorrencias = qtd_atual

            if not df_oc.empty and 'Status_Gestao' in df_oc.columns:
                contagem = df_oc['Aluno'].value_counts()
                filtro_status = st.selectbox("Filtrar:", ["Pendentes", "Arquivados", "Todos"], label_visibility="collapsed")
                
                if filtro_status == "Pendentes": df_show = df_oc[df_oc['Status_Gestao'] != "Arquivado"]
                elif filtro_status == "Arquivados": df_show = df_oc[df_oc['Status_Gestao'] == "Arquivado"]
                else: df_show = df_oc

                if df_show.empty: st.info("Nenhum registro.")
                
                for idx, row in df_show.iloc[::-1].iterrows():
                    sugestao = str(row.get('Acao_Sugerida', ''))
                    badge_class = "badge-media"; badge_text = "MÉDIA"
                    if "Alta" in sugestao: 
                        badge_class = "badge-grave"; badge_text = "GRAVE"
                        if row['Status_Gestao'] != "Arquivado": gerenciar_som("grave", f"g{row['Data']}{row['Aluno']}")
                    elif "Baixa" in sugestao: badge_class = "badge-leve"; badge_text = "LEVE"

                    iniciais = row['Aluno'][:2].upper() if row['Aluno'] else "??"
                    
                    link_whats = None
                    df_c = carregar_alunos_contatos()
                    if not df_c.empty:
                        contato = df_c[df_c['Nome'] == row['Aluno']]
                        if not contato.empty:
                            msg = gerar_mensagem_whats(row['Aluno'], contato.iloc[0]['Responsavel'], row['Descricao'], row.get('Intervencao', 'Em análise'))
                            link_whats = f"https://wa.me/{contato.iloc[0]['Telefone']}?text={urllib.parse.quote(msg)}"

                    st.markdown(f"""
                    <div class="card">
                        <div style="display:flex; justify-content:space-between; align-items:start; margin-bottom:10px;">
                            <div style="display:flex; align-items:center;">
                                <div class="avatar">{iniciais}</div>
                                <div><div style="font-weight:bold; font-size:1.1rem; color:#1F2937;">{row['Aluno']}</div><div style="font-size:0.85rem; color:#6B7280;">{row['Data']} • {row['Turma']}</div></div>
                            </div>
                            <span class="badge {badge_class}">{badge_text}</span>
                        </div>
                        <div style="background:#F9FAFB; padding:15px; border-radius:8px; color:#4B5563; font-size:0.95rem; margin-bottom:15px;">{row['Descricao']}</div>
                        <div style="display:flex; align-items:center; font-size:0.85rem; color:#6366F1; margin-bottom:15px;">✨ <b>Sugestão IA:</b>&nbsp;{sugestao}</div>
                    """, unsafe_allow_html=True)
                    
                    if st.session_state.id_intervencao_ativa == idx:
                        st.markdown("---")
                        txt = st.text_area("Registrar Intervenção:", key=f"tx{idx}")
                        c_s, c_c = st.columns(2)
                        if c_s.button("💾 Salvar e Gerar PDF", key=f"sv{idx}"):
                            atualizar_status_gestao(row['Aluno'], row['Data'], "Arquivado", txt)
                            d_imp = row.to_dict(); d_imp['Intervencao'] = txt
                            st.session_state.pdf_buffer = gerar_pdf_lote(pd.DataFrame([d_imp]))
                            st.session_state.id_intervencao_ativa = None; st.rerun()
                        if c_c.button("Cancelar", key=f"can{idx}"): st.session_state.id_intervencao_ativa = None; st.rerun()
                    else:
                        if 'pdf_buffer' in st.session_state and st.session_state.pdf_buffer:
                            st.success("✅ Documento Gerado!")
                            st.download_button("📥 Baixar Ficha", st.session_state.pdf_buffer, "Ocorrencia.pdf", "application/pdf")
                            if st.button("Fechar"): st.session_state.pdf_buffer = None; st.rerun()
                        elif st.session_state.id_intervencao_ativa is None:
                            cb1, cb2, cb3, cb4 = st.columns([1.5, 1.5, 1, 1])
                            if cb1.button("✅ Resolver", key=f"ok{idx}"): atualizar_status_gestao(row['Aluno'], row['Data'], "Arquivado", "Visto"); st.rerun()
                            if cb2.button("✍️ Intervir", key=f"bi{idx}"): st.session_state.id_intervencao_ativa = idx; st.rerun()
                            if link_whats: cb3.link_button("💬 Zap", link_whats)
                            if cb4.button("🗑️", key=f"d{idx}"): excluir_ocorrencia(row['Aluno'], row['Descricao'][:10]); st.rerun()
                    
                    st.markdown("</div>", unsafe_allow_html=True)
