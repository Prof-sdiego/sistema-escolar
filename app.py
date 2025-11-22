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

# --- CSS PROFISSIONAL ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background-color: #F3F4F6; }
    #MainMenu, footer, header {visibility: hidden;}
    
    .card {
        background-color: white; border-radius: 12px; padding: 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); margin-bottom: 20px; border: 1px solid #F3F4F6;
    }
    .badge { padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; }
    .badge-leve { background-color: #D1FAE5; color: #065F46; }
    .badge-media { background-color: #FEF3C7; color: #92400E; }
    .badge-grave { background-color: #FEE2E2; color: #991B1B; }
    
    /* Avatar */
    .avatar {
        width: 40px; height: 40px; border-radius: 50%; background-color: #E0E7FF; color: #4F46E5;
        display: flex; align-items: center; justify-content: center; font-weight: bold; margin-right: 10px;
    }
    
    @media print {
        @page { size: A4; margin: 0; }
        body * { visibility: hidden; }
        .area-impressao, .area-impressao * { visibility: visible; }
        .area-impressao { position: absolute; left: 0; top: 0; width: 100%; }
    }
</style>
""", unsafe_allow_html=True)

# --- CONEXÃO ---
@st.cache_resource
def conectar():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(st.secrets["service_account_info"]), scope)
    client = gspread.authorize(creds)
    return client.open("Dados_Escolares")

# --- IA AUTO-CONFIG ---
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

# --- DADOS (CACHED) ---
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
def carregar_alunos_db(): 
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

# --- TRANSCRIÇÃO DE ÁUDIO (IA) ---
def transcrever_audio(audio_bytes):
    if not nome_modelo_ativo: return ""
    try:
        modelo = genai.GenerativeModel(nome_modelo_ativo)
        # O Gemini aceita audio e texto juntos
        resp = modelo.generate_content([
            "Transcreva este áudio de ocorrência escolar fielmente. Retorne apenas o texto.",
            {"mime_type": "audio/mp3", "data": audio_bytes}
        ])
        return resp.text
    except: return ""

# --- IA CONSULTA E WHATSAPP ---
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

# --- PDF ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 16); self.cell(0, 10, 'OCORRÊNCIA DIGITAL - RELATÓRIO', 0, 1, 'C'); self.ln(5); self.line(10, 25, 200, 25)
    def footer(self):
        self.set_y(-15); self.set_font('Arial', 'I', 8); self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def desenhar_pagina_ocorrencia(pdf, dados):
    def limpa(t): return str(t).encode('latin-1', 'replace').decode('latin-1')
    pdf.set_font("Arial", size=12)
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, limpa(f"REGISTRO - {dados['Data']}"), 0, 1, 'L', True); pdf.ln(5)
    pdf.set_font("Arial", 'B', 11); pdf.cell(25, 8, "Aluno:", 0, 0); pdf.set_font("Arial", '', 11); pdf.cell(80, 8, limpa(dados['Aluno']), 0, 0)
    pdf.set_font("Arial", 'B', 11); pdf.cell(20, 8, "Turma:", 0, 0); pdf.set_font("Arial", '', 11); pdf.cell(0, 8, limpa(dados['Turma']), 0, 1)
    pdf.line(10, pdf.get_y()+5, 200, pdf.get_y()+5); pdf.ln(10)
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, limpa("DESCRIÇÃO:"), 0, 1)
    pdf.set_font("Arial", '', 11); pdf.multi_cell(0, 6, limpa(dados['Descricao'])); pdf.ln(8)
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, limpa("INTERVENÇÃO:"), 0, 1)
    pdf.set_font("Arial", '', 11); pdf.multi_cell(0, 6, limpa(dados.get('Intervencao', '') or "Sem registro."))
    pdf.set_y(-50); y = pdf.get_y(); pdf.set_font("Arial", '', 9)
    pdf.line(20, y, 90, y); pdf.text(40, y+5, limpa("Aluno(a)"))
    pdf.line(120, y, 190, y); pdf.text(140, y+5, limpa("Responsável"))
    pdf.line(70, y+25, 140, y+25); pdf.text(90, y+30, limpa("Gestão Escolar"))

def gerar_pdf_lote(dataframe_filtrado):
    pdf = PDF()
    for index, row in dataframe_filtrado.iterrows(): pdf.add_page(); desenhar_pagina_ocorrencia(pdf, row.to_dict())
    return pdf.output(dest='S').encode('latin-1')

# --- SOM ---
def gerenciar_som(tipo="normal", chave_evento=None):
    if 'sons_tocados' not in st.session_state: st.session_state.sons_tocados = set()
    if chave_evento in st.session_state.sons_tocados: return
    sound_url = "https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"
    if tipo == "grave": sound_url = "https://assets.mixkit.co/active_storage/sfx/995/995-preview.mp3"
    st.markdown(f"""<audio autoplay><source src="{sound_url}" type="audio/mp3"></audio>""", unsafe_allow_html=True)
    if chave_evento: st.session_state.sons_tocados.add(chave_evento)

# --- STATES ---
if 'panico_mode' not in st.session_state: st.session_state.panico_mode = False
if 'id_intervencao_ativa' not in st.session_state: st.session_state.id_intervencao_ativa = None
if 'total_ocorrencias' not in st.session_state: st.session_state.total_ocorrencias = 0
if 'pdf_buffer' not in st.session_state: st.session_state.pdf_buffer = None
if 'prof_turmas_permitidas' not in st.session_state: st.session_state.prof_turmas_permitidas = []

# Login
params = st.query_params
if "prof_logado" in params: 
    st.session_state.prof_logado = True; st.session_state.prof_nome = params["prof_nome"]
    # Recarrega turmas permitidas se estiver no URL (simplificado, na prática ideal recarregar do DB)
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
            if st.form_submit_button("Entrar"):
                df = carregar_professores()
                if not df.empty:
                    df['Codigo'] = df['Codigo'].astype(str)
                    usuario = df[(df['Nome'] == ln) & (df['Codigo'] == lc)]
                    if not usuario.empty:
                        st.session_state.prof_logado = True; st.session_state.prof_nome = ln
                        
                        # LÓGICA DE TURMAS PERMITIDAS
                        turmas_raw = str(usuario.iloc[0].get('Turmas', '')).strip()
                        if turmas_raw:
                            st.session_state.prof_turmas_permitidas = [t.strip() for t in turmas_raw.split(",") if t.strip()]
                        else:
                            st.session_state.prof_turmas_permitidas = ["6A","6B","7A","7B","8A","8B","9A","9B"] # Default todas
                        
                        st.query_params["prof_logado"] = "true"; st.query_params["prof_nome"] = ln
                        st.rerun()
                    else: st.error("Dados inválidos.")
    else:
        col_h1, col_h2 = st.columns([4,1])
        col_h1.success(f"👤 Prof. **{st.session_state.prof_nome}**")
        if col_h2.button("Sair"): 
            st.session_state.prof_logado = False; st.query_params.clear(); st.rerun()

        tab_reg, tab_hist = st.tabs(["📝 Registrar", "🗂️ Histórico"])

        with tab_reg:
            c1, c2 = st.columns([3,1])
            c1.warning("⚠️ Emergências Graves apenas."); 
            if c2.button("🚨 PÂNICO", type="primary"): st.session_state.panico_mode = True
            
            if st.session_state.panico_mode:
                with st.form("panico"):
                    st.error("CHAMAR GESTÃO?")
                    t = st.selectbox("Sala:", st.session_state.prof_turmas_permitidas)
                    if st.form_submit_button("CONFIRMAR"):
                        salvar_alerta(t, st.session_state.prof_nome)
                        st.toast("🚨 Enviado!", icon="🚨"); time.sleep(2); st.session_state.panico_mode = False; st.rerun()
                    if st.form_submit_button("Cancelar"): st.session_state.panico_mode = False; st.rerun()
            
            st.markdown("---")
            
            # INPUT POR VOZ
            st.write("🎙️ **Ditado Inteligente:**")
            audio_val = st.audio_input("Grave a ocorrência")
            texto_transcrito = ""
            if audio_val:
                with st.spinner("Transcrevendo..."):
                    texto_transcrito = transcrever_audio(audio_val.read())
                    if texto_transcrito: st.success("Áudio convertido!")

            with st.form("form_oc", clear_on_submit=True):
                turma = st.selectbox("Turma", st.session_state.prof_turmas_permitidas)
                
                # LISTA DE ALUNOS INTELIGENTE
                df_alunos = carregar_alunos_db()
                lista_alunos_turma = []
                if not df_alunos.empty and 'Turma' in df_alunos.columns:
                    lista_alunos_turma = sorted(df_alunos[df_alunos['Turma'] == turma]['Nome'].unique().tolist())
                
                col_al1, col_al2 = st.columns([3, 1])
                # Se tiver alunos na DB, mostra selectbox, senão text area
                if lista_alunos_turma:
                    alunos_sel = st.multiselect("Selecione os Alunos:", lista_alunos_turma)
                else:
                    alunos_texto = st.text_area("Alunos (separados por vírgula)", placeholder="Ex: João, Maria")
                    alunos_sel = [] # Placeholder

                descricao = st.text_area("Descrição", value=texto_transcrito, height=150)
                
                if st.form_submit_button("Enviar Ocorrência"):
                    # Consolida lista de alunos
                    final_alunos = alunos_sel if lista_alunos_turma else [n.strip() for n in alunos_texto.split(",") if n.strip()]
                    
                    if final_alunos and descricao:
                        st.toast("✅ Enviado!", icon="🚀")
                        g, a = consultar_ia(descricao, turma)
                        salvar_ocorrencia(final_alunos, turma, st.session_state.prof_nome, descricao, a)
                    else: st.warning("Preencha os campos.")

        with tab_hist:
            df = carregar_ocorrencias_cache()
            if not df.empty:
                meus = df[df['Professor'] == st.session_state.prof_nome]
                for i, row in meus.iloc[::-1].iterrows():
                    cor = "green" if row['Status_Gestao'] == "Arquivado" else "orange"
                    status = "✅ Resolvido" if row['Status_Gestao'] == "Arquivado" else "⏳ Pendente"
                    st.markdown(f"""<div class="card" style="border-left:5px solid {cor}">
                    <b>{row['Aluno']}</b> ({row['Data']}) <span class="badge" style="background:#eee">{status}</span><br>
                    {row['Descricao']}<br><small><b>Gestão:</b> {row.get('Intervencao', 'Aguardando')}</small></div>""", unsafe_allow_html=True)

# ================= GESTÃO =================
elif menu == "Painel Gestão":
    if not st.session_state.gestao_logada:
        with st.form("login_gestao"):
            st.write("### 📊 Acesso Gestão")
            gn = st.text_input("Usuário"); gc = st.text_input("Senha", type="password")
            if st.form_submit_button("Entrar"):
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
                else: st.error("Erro.")
    else:
        col_g1, col_g2 = st.columns([4,1])
        col_g1.info(f"📊 Gestor: **{st.session_state.gestao_nome}**")
        if col_g2.button("Sair", key="sair_gest"): st.session_state.gestao_logada = False; st.query_params.clear(); st.rerun()

        if st.session_state.id_intervencao_ativa is None: st_autorefresh(interval=15000, key="gestaorefresh")

        # ALERTAS
        df_alertas = carregar_alertas()
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

        tab1, tab2, tab3, tab4, tab5 = st.tabs(["🔥 Dashboard", "📝 Registrar", "🏫 Histórico", "🖨️ PDF", "⚙️ Admin"])
        
        df_oc = carregar_ocorrencias_cache()
        
        # ABA 1: DASHBOARD COM GRÁFICOS
        with tab1:
            if not df_oc.empty:
                qtd_atual = len(df_oc)
                if qtd_atual > st.session_state.total_ocorrencias:
                    gerenciar_som("normal", f"n{qtd_atual}"); st.toast("🔔 Nova Ocorrência!"); st.session_state.total_ocorrencias = qtd_atual
                
                # Cards Topo
                kpi1, kpi2, kpi3 = st.columns(3)
                hoje = datetime.now().strftime("%Y-%m-%d")
                total_hoje = len(df_oc[df_oc['Data'].str.contains(hoje)])
                criticos = len(df_oc[df_oc['Acao_Sugerida'].str.contains("Alta", na=False)])
                kpi1.metric("Hoje", total_hoje)
                kpi2.metric("Críticos", criticos)
                kpi3.metric("Total Geral", len(df_oc))
                
                # Gráficos Plotly
                g1, g2 = st.columns(2)
                with g1:
                    fig_bar = px.bar(df_oc['Turma'].value_counts().reset_index(), x='Turma', y='count', title="Ocorrências por Turma")
                    st.plotly_chart(fig_bar, use_container_width=True)
                with g2:
                    fig_pie = px.pie(df_oc, names='Turma', title="Distribuição %")
                    st.plotly_chart(fig_pie, use_container_width=True)

                # Lista Recente
                st.subheader("Feed Recente")
                pend = df_oc[df_oc['Status_Gestao'] != "Arquivado"]
                if pend.empty: st.success("Tudo em ordem.")
                
                for idx, row in pend.iloc[::-1].iterrows():
                    sugestao = str(row.get('Acao_Sugerida', ''))
                    cor = "#fff3cd"
                    if "Alta" in sugestao: cor = "#ffe6e6"; gerenciar_som("grave", f"g{row['Data']}{row['Aluno']}")
                    
                    # WhatsApp
                    link_whats = None
                    df_c = carregar_alunos_contatos()
                    if not df_c.empty:
                        contato = df_c[df_c['Nome'] == row['Aluno']]
                        if not contato.empty:
                            msg = gerar_mensagem_whats(row['Aluno'], contato.iloc[0]['Responsavel'], row['Descricao'], row.get('Intervencao', ''))
                            link_whats = f"https://wa.me/{contato.iloc[0]['Telefone']}?text={urllib.parse.quote(msg)}"

                    with st.container():
                        st.markdown(f"""<div class="card" style="background:{cor}; border-left: 5px solid orange;">
                        <b>{row['Aluno']}</b> ({row['Turma']})<br><i>"{row['Descricao']}"</i><br><small><b>IA:</b> {sugestao}</small></div>""", unsafe_allow_html=True)
                        
                        if st.session_state.id_intervencao_ativa == idx:
                            txt = st.text_area("Intervenção:", key=f"tx{idx}")
                            if st.button("💾 Salvar e Gerar PDF", key=f"sv{idx}"):
                                atualizar_status_gestao(row['Aluno'], row['Data'], "Arquivado", txt)
                                d_imp = row.to_dict(); d_imp['Intervencao'] = txt
                                st.session_state.pdf_buffer = gerar_pdf_lote(pd.DataFrame([d_imp]))
                                st.session_state.id_intervencao_ativa = None; st.rerun()
                        else:
                            if 'pdf_buffer' in st.session_state and st.session_state.pdf_buffer:
                                st.download_button("📥 Baixar PDF", st.session_state.pdf_buffer, "Ocorrencia.pdf", "application/pdf")
                                if st.button("Fechar"): st.session_state.pdf_buffer = None; st.rerun()
                            elif st.session_state.id_intervencao_ativa is None:
                                c1, c2, c3, c4 = st.columns([1,1,1,1])
                                if c1.button("✅ Visto", key=f"ok{idx}"): atualizar_status_gestao(row['Aluno'], row['Data'], "Arquivado", "Visto"); st.rerun()
                                if c2.button("✍️ Intervir", key=f"bi{idx}"): st.session_state.id_intervencao_ativa = idx; st.rerun()
                                if link_whats: c3.link_button("💬 Zap", link_whats)
                                if c4.button("🗑️", key=f"d{idx}"): excluir_ocorrencia(row['Aluno'], row['Descricao'][:10]); st.rerun()

        with tab2: # Registrar
            tg = st.selectbox("Turma", ["6A","6B","7A","7B","8A","8B","9A","9B"], key="treg")
            with st.form("fg", clear_on_submit=True):
                ag = st.text_input("Aluno"); dg = st.text_area("Fato"); ig = st.text_area("Intervenção")
                if st.form_submit_button("Registrar"):
                    g, a = consultar_ia(dg, tg)
                    salvar_ocorrencia([ag], tg, "GESTÃO", dg, a, ig); st.toast("Salvo!"); time.sleep(2); st.rerun()

        with tab3: # Histórico
            if not df_oc.empty:
                t = st.selectbox("Filtrar:", sorted(df_oc['Turma'].astype(str).unique()))
                st.dataframe(df_oc[df_oc['Turma'] == t])
        
        with tab4: # Relatórios
            st.header("🖨️ Central de Relatórios (PDF)")
            tr = st.radio("Modo:", ["Aluno", "Turma"])
            if not df_oc.empty:
                ts = st.selectbox("Turma:", sorted(df_oc['Turma'].astype(str).unique()), key="relt")
                dft = df_oc[df_oc['Turma'] == ts]
                if tr == "Aluno":
                    al = st.selectbox("Aluno:", sorted(dft['Aluno'].unique()))
                    if st.button("Gerar PDF"):
                        pdf = gerar_pdf_lote(dft[dft['Aluno'] == al])
                        st.download_button("📥 Baixar PDF", pdf, f"Rel_{al}.pdf", "application/pdf")
                else:
                    if st.button(f"Gerar PDF Turma ({len(dft)})"):
                        pdf = gerar_pdf_lote(dft)
                        st.download_button("📥 Baixar PDF", pdf, f"Rel_{ts}.pdf", "application/pdf")

        with tab5: # Admin
            st.write("### Cadastrar")
            c1, c2 = st.columns(2)
            with c1:
                with st.form("np"):
                    np = st.text_input("Prof Nome"); cp = st.text_input("Senha")
                    if st.form_submit_button("Salvar"): cadastrar_usuario("Professor", np, cp); st.success("Ok")
            with c2:
                with st.form("ng"):
                    ng = st.text_input("Gestor Nome"); cg = st.text_input("Senha")
                    if st.form_submit_button("Salvar"): cadastrar_usuario("Gestor", ng, cg); st.success("Ok")
