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

# --- CONFIGURAÇÕES GERAIS ---
st.set_page_config(page_title="EduGestor Pro", layout="wide", page_icon="🎓")

# --- CSS ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background-color: #F3F4F6; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    
    .card { background-color: white; border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); margin-bottom: 20px; border: 1px solid #F3F4F6; }
    .badge { padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; }
    .badge-leve { background-color: #D1FAE5; color: #065F46; }
    .badge-media { background-color: #FEF3C7; color: #92400E; }
    .badge-grave { background-color: #FEE2E2; color: #991B1B; }
    .avatar { width: 40px; height: 40px; border-radius: 50%; background-color: #E0E7FF; color: #4F46E5; display: flex; align-items: center; justify-content: center; font-weight: bold; margin-right: 10px; }
    .ai-card { background: linear-gradient(135deg, #6366F1 0%, #4F46E5 100%); border-radius: 16px; padding: 25px; color: white; margin-bottom: 20px; box-shadow: 0 10px 15px -3px rgba(79, 70, 229, 0.4); }
    .ai-card h3 { color: white !important; margin: 0 0 10px 0; }
    .ai-card p { color: #E0E7FF; font-size: 0.9rem; }
    @media print { @page { size: A4; margin: 0; } body * { visibility: hidden; } }
</style>
""", unsafe_allow_html=True)

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

# --- DADOS ---
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

# --- ESCRITA ---
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

def atualizar_status_gestao(aluno, data_ocorrencia, novo_status, intervencao_texto=None):
    try:
        wb = conectar(); sheet = wb.sheet1; cell = sheet.find(data_ocorrencia)
        if cell:
            nome_na_planilha = sheet.cell(cell.row, 2).value
            if nome_na_planilha == aluno:
                sheet.update_cell(cell.row, 8, novo_status)
                if intervencao_texto: sheet.update_cell(cell.row, 7, intervencao_texto)
                limpar_cache(); return True
    except: pass
    return False

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

# --- PDF (FPDF) ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 16); self.cell(0, 10, 'EDUGESTOR - RELATÓRIO ESCOLAR', 0, 1, 'C'); self.ln(5); self.line(10, 25, 200, 25); self.ln(10)
    def footer(self):
        self.set_y(-15); self.set_font('Arial', 'I', 8); self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def desenhar_pagina_ocorrencia(pdf, dados):
    def limpa(t): return str(t).encode('latin-1', 'replace').decode('latin-1')
    if pdf.get_y() > 230: pdf.add_page()
    
    pdf.set_fill_color(245, 245, 245)
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(0, 8, limpa(f"DATA: {dados['Data']} | PROFESSOR: {dados['Professor']}"), 0, 1, 'L', True)
    pdf.set_font("Arial", '', 10)
    pdf.multi_cell(0, 6, limpa(f"FATOS: {dados['Descricao']}"))
    pdf.ln(2)
    pdf.set_font("Arial", 'I', 10)
    interv = dados.get('Intervencao', '') or "Sem registro."
    pdf.multi_cell(0, 6, limpa(f"INTERVENÇÃO: {interv}"))
    pdf.ln(2); pdf.line(10, pdf.get_y(), 200, pdf.get_y()); pdf.ln(5)

def imprimir_assinaturas(pdf):
    if pdf.get_y() > 240: pdf.add_page()
    pdf.ln(10); y = pdf.get_y(); pdf.set_font("Arial", '', 9)
    pdf.line(20, y, 80, y); pdf.text(35, y+5, "Aluno(a)")
    pdf.line(120, y, 180, y); pdf.text(135, y+5, "Responsável")
    pdf.ln(20); pdf.line(70, pdf.get_y(), 140, pdf.get_y()); pdf.text(90, pdf.get_y()+5, "Gestão Escolar")

def gerar_pdf_continuo(df_dados, titulo_extra=""):
    pdf = PDF(); pdf.add_page()
    def limpa(t): return str(t).encode('latin-1', 'replace').decode('latin-1')
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, limpa(titulo_extra), 0, 1, 'L'); pdf.ln(5)
    for _, row in df_dados.iterrows(): desenhar_pagina_ocorrencia(pdf, row.to_dict())
    imprimir_assinaturas(pdf)
    return pdf.output(dest='S').encode('latin-1')

def gerar_pdf_turma_completa(df_turma):
    pdf = PDF(); alunos_unicos = sorted(df_turma['Aluno'].unique())
    def limpa(t): return str(t).encode('latin-1', 'replace').decode('latin-1')
    for aluno in alunos_unicos:
        pdf.add_page(); pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, limpa(f"ALUNO: {aluno}"), 0, 1, 'L'); pdf.line(10, pdf.get_y(), 200, pdf.get_y()); pdf.ln(5)
        ocorrencias_aluno = df_turma[df_turma['Aluno'] == aluno]
        for _, row in ocorrencias_aluno.iterrows(): desenhar_pagina_ocorrencia(pdf, row.to_dict())
        imprimir_assinaturas(pdf)
    return pdf.output(dest='S').encode('latin-1')

# --- ESTADOS ---
if 'panico_mode' not in st.session_state: st.session_state.panico_mode = False
if 'id_intervencao_ativa' not in st.session_state: st.session_state.id_intervencao_ativa = None
if 'total_ocorrencias' not in st.session_state: st.session_state.total_ocorrencias = 0
if 'pdf_buffer' not in st.session_state: st.session_state.pdf_buffer = None
if 'prof_turmas_permitidas' not in st.session_state: st.session_state.prof_turmas_permitidas = []

params = st.query_params
if "prof_logado" in params: st.session_state.prof_logado = True; st.session_state.prof_nome = params["prof_nome"]
if 'prof_logado' not in st.session_state: st.session_state.prof_logado = False
if "gestao_logada" in params: st.session_state.gestao_logada = True; st.session_state.gestao_nome = params["gestao_nome"]
if 'gestao_logada' not in st.session_state: st.session_state.gestao_logada = False

# --- INTERFACE ---
st.title("🏫 EduGestor Pro")
menu = st.sidebar.radio("Menu", ["Acesso Professor", "Painel Gestão"])

# ================= PROFESSOR =================
if menu == "Acesso Professor":
    if not st.session_state.prof_logado:
        with st.form("login_prof"):
            st.write("### 🔐 Acesso Professor")
            ln = st.text_input("Nome"); lc = st.text_input("Código", type="password")
            if st.form_submit_button("Entrar", type="primary"):
                df = carregar_professores()
                if not df.empty:
                    df['Codigo'] = df['Codigo'].astype(str)
                    usuario = df[(df['Nome'] == ln) & (df['Codigo'] == lc)]
                    if not usuario.empty:
                        st.session_state.prof_logado = True; st.session_state.prof_nome = ln
                        turmas_raw = str(usuario.iloc[0].get('Turmas', '')).strip()
                        if turmas_raw: st.session_state.prof_turmas_permitidas = [t.strip() for t in turmas_raw.split(",") if t.strip()]
                        else: st.session_state.prof_turmas_permitidas = ["6A","6B","7A","7B","8A","8B","9A","9B"]
                        st.query_params["prof_logado"] = "true"; st.query_params["prof_nome"] = ln; st.rerun()
                    else: st.error("Dados inválidos.")
                else: st.error("Erro conexão.")
    else:
        if not st.session_state.prof_turmas_permitidas: st.session_state.prof_turmas_permitidas = ["6A","6B","7A","7B","8A","8B","9A","9B"]
        c_head1, c_head2 = st.columns([5,1])
        with c_head1: st.markdown(f"## Olá, **{st.session_state.prof_nome}**")
        with c_head2: 
            if st.button("Sair", key="sair_p"): st.session_state.prof_logado = False; st.query_params.clear(); st.rerun()

        tab_reg, tab_hist = st.tabs(["📝 Registrar", "🗂️ Histórico"])

        with tab_reg:
            with st.expander("🚨 CHAMAR GESTÃO"):
                if st.button("CHAMAR AJUDA AGORA", type="primary"):
                    salvar_alerta("Sala Indefinida", st.session_state.prof_nome); st.toast("🚨 Enviado!", icon="🚨")

            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.write("🎙️ **Ditado Inteligente:**")
            audio_val = st.audio_input("Gravar")
            texto_transcrito = ""
            if audio_val:
                with st.spinner("Transcrevendo..."): texto_transcrito = transcrever_audio(audio_val.read())

            # --- SELEÇÃO DE TURMA FORA DO FORM (PARA REFRESH) ---
            turma_sel = st.selectbox("Selecione a Turma:", st.session_state.prof_turmas_permitidas)
            
            # --- LÓGICA DE FILTRO DE ALUNOS (ROBUSTA) ---
            df_alunos = carregar_alunos_contatos()
            lista_alunos_turma = []
            if not df_alunos.empty and 'Turma' in df_alunos.columns and 'Nome' in df_alunos.columns:
                df_alunos['Turma_Limpa'] = df_alunos['Turma'].astype(str).str.strip().str.upper()
                turma_filtro = str(turma_sel).strip().upper()
                lista_alunos_turma = sorted(df_alunos[df_alunos['Turma_Limpa'] == turma_filtro]['Nome'].unique().tolist())

            with st.form("form_oc", clear_on_submit=True):
                st.markdown("#### Nova Ocorrência")
                
                if lista_alunos_turma:
                    alunos_input = st.multiselect("Selecione os Alunos:", lista_alunos_turma)
                    alunos_texto = ""
                else:
                    st.warning("⚠️ Nenhum aluno encontrado nesta turma na planilha. Digite abaixo:")
                    alunos_texto = st.text_area("Alunos (separados por vírgula)", placeholder="Ex: João, Maria")
                    alunos_input = []

                descricao = st.text_area("Descrição Detalhada do Fato", value=texto_transcrito, height=150)
                
                if st.form_submit_button("Enviar Ocorrência", type="primary"):
                    final = alunos_input if lista_alunos_turma else [x.strip() for x in alunos_texto.split(',') if x.strip()]
                    if final and descricao:
                        st.toast("✅ Enviado!", icon="🚀")
                        g, a = consultar_ia(descricao, turma_sel)
                        salvar_ocorrencia(final, turma_sel, st.session_state.prof_nome, descricao, a)
                    else: st.warning("Preencha todos os campos.")
            st.markdown('</div>', unsafe_allow_html=True)

        with tab_hist:
            df = carregar_ocorrencias_cache()
            if not df.empty:
                for i, r in df[df['Professor'] == st.session_state.prof_nome].iloc[::-1].iterrows():
                    cor = "green" if r['Status_Gestao'] == "Arquivado" else "orange"
                    st.markdown(f"""<div class="card" style="border-left:5px solid {cor}">
                    <b>{r['Aluno']}</b> ({r['Data']})<br>{r['Descricao']}<br><small><b>Gestão:</b> {r.get('Intervencao', 'Aguardando')}</small></div>""", unsafe_allow_html=True)

# ================= GESTÃO =================
elif menu == "Painel Gestão":
    if not st.session_state.gestao_logada:
        c1, c2, c3 = st.columns([1,2,1])
        with c2:
            st.markdown("### 📊 Gestão")
            with st.form("lg"):
                gn = st.text_input("Usuário"); gc = st.text_input("Senha", type="password")
                if st.form_submit_button("Entrar", type="primary"):
                    hash_real = "0b3ea097e02015db007c4b357e12692702b2226633299d0775907ff424a06e30"
                    login_ok = False
                    if hashlib.sha256(gc.encode()).hexdigest() == hash_real: login_ok = True
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
        col_g1, col_g2 = st.columns([4,1])
        col_g1.info(f"Gestor: **{st.session_state.gestao_nome}**")
        if col_g2.button("Sair"): st.session_state.gestao_logada = False; st.query_params.clear(); st.rerun()

        if st.session_state.id_intervencao_ativa is None: st_autorefresh(interval=15000, key="gestaorefresh")

        df_alertas = carregar_alertas()
        if not df_alertas.empty:
            for i, row in df_alertas[df_alertas['Status'].isin(["Pendente", "Em Atendimento"])].iterrows():
                st.error(f"🚨 SALA {row['Turma']} ({row['Professor']})")
                if row['Status'] == "Pendente":
                    gerenciar_som("grave", f"p{row['Data']}")
                    if st.button("Atender", key=f"v{i}"): atualizar_alerta_status(row['Turma'], "Em Atendimento"); st.rerun()

        tab1, tab2, tab3, tab4 = st.tabs(["🔥 Feed", "🏫 Histórico", "🖨️ Relatórios", "⚙️ Admin"])
        
        df_oc = carregar_ocorrencias_cache()
        
        with tab1:
            if not df_oc.empty and 'Status_Gestao' in df_oc.columns:
                f_st = st.selectbox("Visualizar:", ["Pendentes", "Arquivados", "Todos"])
                df_show = df_oc
                if f_st == "Pendentes": df_show = df_oc[df_oc['Status_Gestao'].fillna("Pendente").isin(["Pendente", ""])]
                elif f_st == "Arquivados": df_show = df_oc[df_oc['Status_Gestao'] == "Arquivado"]
                
                if df_show.empty: st.success("Tudo em ordem.")
                
                # Verifica novidades
                pendentes_geral = df_oc[df_oc['Status_Gestao'].isin(["Pendente", ""])]
                if len(pendentes_geral) > st.session_state.total_ocorrencias:
                    gerenciar_som("normal", f"n{len(pendentes_geral)}"); st.toast("🔔 Nova Ocorrência!"); st.session_state.total_ocorrencias = len(pendentes_geral)

                for idx, row in df_show.iloc[::-1].iterrows():
                    cor = "#ffe6e6" if "Alta" in str(row.get('Acao_Sugerida')) else "#fff3cd"
                    if "Alta" in str(row.get('Acao_Sugerida')) and f_st != "Arquivados": 
                        gerenciar_som("grave", f"g{row['Data']}{row['Aluno']}")

                    with st.container():
                        st.markdown(f"""<div class="card" style="background:{cor}; border-left:5px solid orange">
                        <b>{row['Aluno']}</b> ({row['Turma']})<br><i>"{row['Descricao']}"</i></div>""", unsafe_allow_html=True)
                        
                        if st.session_state.id_intervencao_ativa == idx:
                            txt = st.text_area("Ação:", key=f"tx{idx}")
                            if st.button("Salvar", key=f"sv{idx}"):
                                atualizar_status_gestao(row['Aluno'], row['Data'], "Arquivado", txt)
                                st.session_state.pdf_buffer = gerar_pdf_continuo(pd.DataFrame([row.to_dict() | {'Intervencao': txt}]))
                                st.session_state.id_intervencao_ativa = None; st.rerun()
                        else:
                            if st.button("Intervir", key=f"b{idx}"): st.session_state.id_intervencao_ativa = idx; st.rerun()

        with tab2: 
            if not df_oc.empty: st.dataframe(df_oc)

        with tab3:
            st.header("🖨️ Relatórios (PDF)")
            if not df_oc.empty:
                mod = st.radio("Modo:", ["Por Aluno", "Por Turma"])
                ts = st.selectbox("Turma:", sorted(df_oc['Turma'].astype(str).unique()))
                dft = df_oc[df_oc['Turma'] == ts]
                
                if mod == "Por Aluno":
                    al = st.selectbox("Aluno:", sorted(dft['Aluno'].unique()))
                    if st.button("Gerar PDF Aluno"):
                        pdf = gerar_pdf_continuo(dft[dft['Aluno'] == al], f"RELATÓRIO INDIVIDUAL: {al}")
                        st.download_button("📥 Baixar", pdf, "Rel_Aluno.pdf", "application/pdf")
                else:
                    if st.button("Gerar PDF Turma"):
                        pdf = gerar_pdf_turma_completa(dft)
                        st.download_button("📥 Baixar Turma", pdf, "Rel_Turma.pdf", "application/pdf")

        with tab4:
            with st.form("new_usr"):
                tp = st.selectbox("Tipo", ["Professor", "Gestor"])
                nm = st.text_input("Nome"); cd = st.text_input("Senha")
                if st.form_submit_button("Criar"): cadastrar_usuario(tp, nm, cd); st.success("Ok")
