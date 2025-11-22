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
import re

# --- CONFIGURAÇÕES GERAIS ---
st.set_page_config(page_title="EduGestor Pro", layout="wide", page_icon="🎓")

# --- INJEÇÃO DE JAVASCRIPT (NOTIFICAÇÕES DESKTOP) ---
# Isso permite que o site mande avisos do Windows/Mac mesmo minimizado
js_notification = """
<script>
    function requestNotificationPermission() {
        if (!("Notification" in window)) {
            alert("Este navegador não suporta notificações de desktop");
        } else if (Notification.permission !== "granted") {
            Notification.requestPermission();
        }
    }
    requestNotificationPermission();
    
    function sendNotification(title, body) {
        if (Notification.permission === "granted") {
            new Notification(title, {
                body: body,
                icon: "https://cdn-icons-png.flaticon.com/512/2991/2991110.png"
            });
        }
    }
</script>
"""
st.components.v1.html(js_notification, height=0)

# --- CSS (VISUAL) ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background-color: #F3F4F6; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    
    .card {
        background-color: white; border-radius: 12px; padding: 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); margin-bottom: 20px; border: 1px solid #F3F4F6;
    }
    .badge { padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; }
    .badge-leve { background-color: #D1FAE5; color: #065F46; }
    .badge-media { background-color: #FEF3C7; color: #92400E; }
    .badge-grave { background-color: #FEE2E2; color: #991B1B; }
    
    .avatar {
        width: 40px; height: 40px; border-radius: 50%; background-color: #E0E7FF; color: #4F46E5;
        display: flex; align-items: center; justify-content: center; font-weight: bold; margin-right: 10px;
    }
    
    .ai-card {
        background: linear-gradient(135deg, #6366F1 0%, #4F46E5 100%);
        border-radius: 16px; padding: 25px; color: white; margin-bottom: 20px;
        box-shadow: 0 10px 15px -3px rgba(79, 70, 229, 0.4);
    }
    .ai-card h3 { color: white !important; margin: 0 0 10px 0; }
    .ai-card p { color: #E0E7FF; font-size: 0.9rem; }

    /* Notificação de Encaminhamento */
    .encaminhamento {
        border: 2px dashed #F59E0B; background-color: #FFFBEB; padding: 10px; border-radius: 8px; margin-top: 5px; font-weight: bold; color: #92400E;
    }

    @media print {
        @page { size: A4; margin: 0; }
        body * { visibility: hidden; }
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

# --- IA (CONFIGURAÇÃO) ---
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
        return pd.DataFrame(d) if d else pd.DataFrame(columns=["Data", "Aluno", "Turma", "Professor", "Descricao", "Acao_Sugerida", "Intervencao", "Status_Gestao", "Encaminhado"])
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

def salvar_ocorrencia(alunos_lista, turma, prof, desc, acao, encaminhado="Não", intervencao=""):
    try:
        sheet = conectar().sheet1
        data = datetime.now().strftime("%Y-%m-%d %H:%M")
        # Se a planilha não tiver a coluna 'Encaminhado' (coluna I / 9), vamos assumir que é a última
        # Recomendo criar na planilha a coluna "Encaminhado" depois de "Status_Gestao"
        for aluno in alunos_lista:
            aluno_limpo = aluno.strip()
            if aluno_limpo:
                # Adiciona linha: Data, Aluno, Turma, Prof, Desc, Acao, Intervencao, Status, Encaminhado
                sheet.append_row([data, aluno_limpo, turma, prof, desc, acao, intervencao, "Pendente", encaminhado])
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
        limpar_cache() # Importante para atualizar a UI
    except: pass

def cadastrar_usuario(tipo, nome, codigo):
    try:
        aba = "Professores" if tipo == "Professor" else "Gestores"
        conectar().worksheet(aba).append_row([nome, codigo])
        limpar_cache(); return True
    except: return False

# --- SOM & NOTIFICAÇÃO ---
def disparar_alerta(tipo="normal", titulo="Nova Ocorrência", corpo="Verifique o painel"):
    """Toca som e manda notificação Windows"""
    sound_url = "https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3" # Ding
    if tipo == "grave": sound_url = "https://assets.mixkit.co/active_storage/sfx/995/995-preview.mp3" # Sirene
    elif tipo == "encaminhado": sound_url = "https://assets.mixkit.co/active_storage/sfx/1862/1862-preview.mp3" # Campainha
    
    # Audio Invisível
    st.markdown(f"""<audio autoplay><source src="{sound_url}" type="audio/mp3"></audio>""", unsafe_allow_html=True)
    
    # Notificação JS
    st.markdown(f"""<script>sendNotification("{titulo}", "{corpo}");</script>""", unsafe_allow_html=True)

def gerenciar_notificacoes_gestao(df_oc, df_alertas):
    """Lógica central de notificações para não repetir sons"""
    if 'historico_notificacoes' not in st.session_state: st.session_state.historico_notificacoes = set()
    
    # 1. Alertas de Pânico Pendentes
    if not df_alertas.empty:
        pendentes = df_alertas[df_alertas['Status'] == "Pendente"]
        for _, row in pendentes.iterrows():
            chave = f"panico_{row['Data']}_{row['Turma']}"
            if chave not in st.session_state.historico_notificacoes:
                disparar_alerta("grave", "🚨 PÂNICO NA SALA", f"Prof. {row['Professor']} pede ajuda na {row['Turma']}")
                st.session_state.historico_notificacoes.add(chave)
    
    # 2. Novas Ocorrências / Encaminhamentos
    if not df_oc.empty and 'Status_Gestao' in df_oc.columns:
        # Pega pendentes
        pendentes = df_oc[df_oc['Status_Gestao'].isin(["Pendente", ""])]
        for _, row in pendentes.iterrows():
            chave = f"oc_{row['Data']}_{row['Aluno']}"
            if chave not in st.session_state.historico_notificacoes:
                # Verifica se é Encaminhamento
                encaminhado = str(row.get('Encaminhado', 'Não'))
                if encaminhado == "Sim":
                    disparar_alerta("encaminhado", "🚶 Aluno a Caminho", f"{row['Aluno']} foi enviado para a direção.")
                elif "Alta" in str(row.get('Acao_Sugerida')):
                    disparar_alerta("grave", "🔴 Ocorrência Grave", f"{row['Aluno']} - {row['Turma']}")
                else:
                    disparar_alerta("normal", "📝 Nova Ocorrência", f"{row['Aluno']} - {row['Turma']}")
                
                st.session_state.historico_notificacoes.add(chave)

# --- IA (TRANSCRIÇÃO + EXTRAÇÃO DE DADOS) ---
def analisar_comando_voz(audio_bytes):
    if not nome_modelo_ativo: return None
    try:
        modelo = genai.GenerativeModel(nome_modelo_ativo)
        prompt = """
        Analise o áudio. Extraia as seguintes informações em formato JSON:
        {
            "texto_completo": "transcrição fiel do que foi dito",
            "turma_detectada": "ex: 6A, 7B (se mencionado)",
            "alunos_detectados": ["nome1", "nome2"] (se mencionados)
        }
        Se não detectar turma ou aluno, deixe o campo null.
        """
        resp = modelo.generate_content([prompt, {"mime_type": "audio/mp3", "data": audio_bytes}])
        texto_limpo = resp.text.replace("```json", "").replace("```", "")
        return json.loads(texto_limpo)
    except: return None

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

# --- PDF ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 16); self.cell(0, 10, 'RELATÓRIO ESCOLAR - CONVIVA', 0, 1, 'C'); self.ln(5); self.line(10, 25, 200, 25); self.ln(10)
    def footer(self):
        self.set_y(-15); self.set_font('Arial', 'I', 8); self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def imprimir_bloco(pdf, dados):
    def limpa(t): return str(t).encode('latin-1', 'replace').decode('latin-1')
    if pdf.get_y() > 230: pdf.add_page()
    pdf.set_fill_color(240, 240, 240); pdf.set_font("Arial", 'B', 11)
    pdf.cell(0, 8, limpa(f"DATA: {dados['Data']} | PROF: {dados['Professor']}"), 0, 1, 'L', True)
    pdf.set_font("Arial", '', 10); pdf.multi_cell(0, 6, limpa(f"FATO: {dados['Descricao']}"))
    pdf.set_font("Arial", 'I', 10); pdf.multi_cell(0, 6, limpa(f"INTERVENÇÃO: {dados.get('Intervencao', 'S/ Registro')}"))
    pdf.ln(2); pdf.line(10, pdf.get_y(), 200, pdf.get_y()); pdf.ln(5)

def imprimir_assinaturas(pdf):
    if pdf.get_y() > 240: pdf.add_page()
    pdf.ln(10); y = pdf.get_y(); pdf.set_font("Arial", '', 9)
    pdf.line(20, y, 80, y); pdf.text(35, y+5, "Aluno")
    pdf.line(120, y, 180, y); pdf.text(135, y+5, "Responsável")
    pdf.ln(20); pdf.line(70, pdf.get_y(), 140, pdf.get_y()); pdf.text(90, pdf.get_y()+5, "Gestão")

def gerar_pdf_continuo(df_dados, titulo=""):
    pdf = PDF(); pdf.add_page(); 
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, titulo.encode('latin-1', 'replace').decode('latin-1'), 0, 1); pdf.ln(5)
    for _, row in df_dados.iterrows(): imprimir_bloco(pdf, row.to_dict())
    imprimir_assinaturas(pdf)
    return pdf.output(dest='S').encode('latin-1')

def gerar_pdf_conselho(df_turma, turma_nome):
    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, f"RELATÓRIO CONSELHO DE CLASSE - {turma_nome}", 0, 1, 'C'); pdf.ln(10)
    
    # Resumo
    alunos_prob = df_turma['Aluno'].value_counts().head(5)
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, "ALUNOS COM MAIS REGISTROS:", 0, 1)
    pdf.set_font("Arial", '', 11)
    for aluno, qtd in alunos_prob.items():
        pdf.cell(0, 8, f"{aluno.encode('latin-1', 'replace').decode('latin-1')}: {qtd} ocorrencias", 0, 1)
    pdf.ln(10)
    
    # Detalhado
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, "DETALHAMENTO POR ALUNO:", 0, 1)
    alunos_unicos = sorted(df_turma['Aluno'].unique())
    for aluno in alunos_unicos:
        if pdf.get_y() > 250: pdf.add_page()
        pdf.set_font("Arial", 'B', 11); pdf.cell(0, 8, f">> {aluno.encode('latin-1', 'replace').decode('latin-1')}", 0, 1)
        oc_aluno = df_turma[df_turma['Aluno'] == aluno]
        for _, row in oc_aluno.iterrows():
            imprimir_bloco(pdf, row.to_dict())
            
    return pdf.output(dest='S').encode('latin-1')

# --- SESSÃO ---
if 'panico_mode' not in st.session_state: st.session_state.panico_mode = False
if 'id_intervencao_ativa' not in st.session_state: st.session_state.id_intervencao_ativa = None
if 'pdf_buffer' not in st.session_state: st.session_state.pdf_buffer = None
if 'prof_turmas_permitidas' not in st.session_state: st.session_state.prof_turmas_permitidas = []
if 'form_rascunho_desc' not in st.session_state: st.session_state.form_rascunho_desc = ""

# Login
params = st.query_params
if "prof_logado" in params: st.session_state.prof_logado = True; st.session_state.prof_nome = params["prof_nome"]
if 'prof_logado' not in st.session_state: st.session_state.prof_logado = False
if "gestao_logada" in params: st.session_state.gestao_logada = True; st.session_state.gestao_nome = params["gestao_nome"]
if 'gestao_logada' not in st.session_state: st.session_state.gestao_logada = False

# --- INTERFACE ---
st.title("🏫 Ocorrência Digital")
menu = st.sidebar.radio("Menu", ["Acesso Professor", "Painel Gestão"])

# ================= PROFESSOR =================
if menu == "Acesso Professor":
    if not st.session_state.prof_logado:
        with st.form("login_prof"):
            st.write("### 🔐 Acesso Professor"); ln = st.text_input("Nome"); lc = st.text_input("Código", type="password")
            if st.form_submit_button("Entrar", type="primary"):
                df = carregar_professores()
                if not df.empty:
                    df['Codigo'] = df['Codigo'].astype(str)
                    user = df[(df['Nome'] == ln) & (df['Codigo'] == lc)]
                    if not user.empty:
                        st.session_state.prof_logado = True; st.session_state.prof_nome = ln
                        tr = str(user.iloc[0].get('Turmas', '')).strip()
                        st.session_state.prof_turmas_permitidas = [t.strip() for t in tr.split(",")] if tr else ["6A","6B","7A","7B","8A","8B","9A","9B"]
                        st.query_params["prof_logado"] = "true"; st.query_params["prof_nome"] = ln; st.rerun()
                    else: st.error("Dados inválidos.")
    else:
        if not st.session_state.prof_turmas_permitidas: st.session_state.prof_turmas_permitidas = ["6A","6B","7A","7B","8A","8B","9A","9B"]
        c1, c2 = st.columns([5,1]); c1.markdown(f"## Olá, **{st.session_state.prof_nome}**"); 
        if c2.button("Sair"): st.session_state.prof_logado = False; st.query_params.clear(); st.rerun()

        tab_reg, tab_hist = st.tabs(["📝 Registrar", "🗂️ Histórico"])

        with tab_reg:
            # PÂNICO
            with st.expander("🚨 CHAMAR GESTÃO", expanded=False):
                st.warning("Use apenas em emergências.")
                c_p1, c_p2 = st.columns([3, 1])
                turma_panico = c_p1.selectbox("Onde você está?", st.session_state.prof_turmas_permitidas, key="tp")
                if c_p2.button("CHAMAR AGORA", type="primary"):
                    salvar_alerta(turma_panico, st.session_state.prof_nome); st.toast("🚨 Enviado!"); time.sleep(1)

            st.markdown('<div class="card">', unsafe_allow_html=True)
            
            # VOZ
            st.write("🎙️ **Voz Inteligente:**")
            audio_val = st.audio_input("Fale a ocorrência (Ex: 'O Pedro da 6A brigou')")
            dados_voz = {}
            if audio_val:
                with st.spinner("Processando..."):
                    dados_voz = analisar_comando_voz(audio_val.read())
                    if dados_voz: 
                        st.success("Entendido!")
                        st.session_state.form_rascunho_desc = dados_voz.get('texto_completo', '')

            # FORMULÁRIO
            # Selectbox da turma fora do form para atualizar a lista de alunos
            turma_pre = dados_voz.get('turma_detectada') if dados_voz else None
            idx_t = 0
            if turma_pre and turma_pre in st.session_state.prof_turmas_permitidas:
                idx_t = st.session_state.prof_turmas_permitidas.index(turma_pre)
            
            turma_sel = st.selectbox("Turma:", st.session_state.prof_turmas_permitidas, index=idx_t)
            
            # Carrega alunos
            df_a = carregar_alunos_contatos()
            lista_alunos = []
            if not df_a.empty:
                df_a['Turma'] = df_a['Turma'].astype(str).str.strip().str.upper()
                lista_alunos = sorted(df_a[df_a['Turma'] == str(turma_sel).strip().upper()]['Nome'].unique().tolist())
            
            # Lista com opção "Outros"
            lista_com_outros = ["OUTROS (Digitar Nome)"] + lista_alunos
            
            # Pre-seleção de aluno por voz
            alunos_voz = dados_voz.get('alunos_detectados', [])
            default_alunos = [a for a in alunos_voz if a in lista_alunos]

            with st.form("form_oc", clear_on_submit=True):
                st.markdown("#### Detalhes")
                
                alunos_sel = st.multiselect("Alunos:", lista_com_outros, default=default_alunos)
                
                # Lógica para campo manual se escolher "OUTROS" ou lista vazia
                alunos_manual = ""
                if "OUTROS (Digitar Nome)" in alunos_sel or not lista_alunos:
                    alunos_manual = st.text_input("Digite os nomes (separados por vírgula):")
                
                # Histórico Imediato
                if alunos_sel:
                    df_hist = carregar_ocorrencias_cache()
                    if not df_hist.empty:
                        nomes_limpos = [n for n in alunos_sel if n != "OUTROS (Digitar Nome)"]
                        total_prev = len(df_hist[df_hist['Aluno'].isin(nomes_limpos)])
                        if total_prev > 0:
                            st.info(f"⚠️ Histórico: Estes alunos já possuem {total_prev} ocorrências registradas.")

                encaminhar = st.checkbox("🚶 Encaminhar aluno para a Direção agora?")
                
                # Rascunho automático no value
                desc = st.text_area("Descrição:", value=st.session_state.form_rascunho_desc, height=150, key="txt_desc")
                
                if st.form_submit_button("Enviar", type="primary"):
                    # Processa lista final
                    final = [n for n in alunos_sel if n != "OUTROS (Digitar Nome)"]
                    if alunos_manual: final.extend([x.strip() for x in alunos_manual.split(',') if x.strip()])
                    
                    if final and desc:
                        g, a = consultar_ia(desc, turma_sel)
                        enc_str = "Sim" if encaminhar else "Não"
                        salvar_ocorrencia(final, turma_sel, st.session_state.prof_nome, desc, a, enc_str)
                        st.toast("Salvo!"); st.session_state.form_rascunho_desc = "" # Limpa rascunho
                        time.sleep(1)
                    else: st.warning("Preencha alunos e descrição.")
            st.markdown('</div>', unsafe_allow_html=True)

        with tab_hist:
            df = carregar_ocorrencias_cache()
            if not df.empty:
                for i, r in df[df['Professor'] == st.session_state.prof_nome].iloc[::-1].iterrows():
                    cor = "green" if r['Status_Gestao'] == "Arquivado" else "orange"
                    st.markdown(f"""<div class="card" style="border-left:5px solid {cor}"><b>{r['Aluno']}</b> ({r['Data']})<br>{r['Descricao']}<br><small>Gestão: {r.get('Intervencao', '')}</small></div>""", unsafe_allow_html=True)

# ================= GESTÃO =================
elif menu == "Painel Gestão":
    if not st.session_state.gestao_logada:
        c1, c2, c3 = st.columns([1,2,1])
        with c2:
            st.markdown("### 📊 Gestão"); 
            with st.form("lg"):
                gn = st.text_input("Usuário"); gc = st.text_input("Senha", type="password")
                if st.form_submit_button("Entrar", type="primary"):
                    df_g = carregar_gestores()
                    login_ok = False
                    if not df_g.empty:
                        df_g['Codigo'] = df_g['Codigo'].astype(str)
                        if not df_g[(df_g['Nome'] == gn) & (df_g['Codigo'] == gc)].empty: login_ok = True
                    if login_ok:
                        st.session_state.gestao_logada = True; st.session_state.gestao_nome = gn
                        st.query_params["gestao_logada"] = "true"; st.query_params["gestao_nome"] = gn; st.rerun()
                    else: st.error("Erro.")
    else:
        c1, c2 = st.columns([5,1]); c1.info(f"Gestor: **{st.session_state.gestao_nome}**")
        if c2.button("Sair"): st.session_state.gestao_logada = False; st.query_params.clear(); st.rerun()

        if st.session_state.id_intervencao_ativa is None: st_autorefresh(interval=10000, key="gestaorefresh")

        # LÓGICA DE NOTIFICAÇÃO
        df_oc = carregar_ocorrencias_cache()
        df_alertas = carregar_alertas()
        gerenciar_notificacoes_gestao(df_oc, df_alertas)

        # ALERTAS UI
        if not df_alertas.empty:
            for i, row in df_alertas[df_alertas['Status'].isin(["Pendente", "Em Atendimento"])].iterrows():
                st.error(f"🚨 SALA {row['Turma']} ({row['Professor']})")
                c_a, c_b = st.columns(2)
                # CORREÇÃO LÓGICA BOTOES
                if row['Status'] == "Pendente":
                    if c_a.button("Atender", key=f"at{i}"): atualizar_alerta_status(row['Turma'], "Em Atendimento"); st.rerun()
                else: # Em Atendimento
                    if c_a.button("✅ Resolver", key=f"res{i}"): atualizar_alerta_status(row['Turma'], "Resolvido"); st.rerun()
                    if c_b.button("📝 Ocorrência", key=f"reg{i}"): st.info("Preencha na aba Registrar"); st.rerun()

        tab1, tab2, tab3, tab4, tab5 = st.tabs(["🔥 Feed", "🏫 Histórico", "🖨️ Relatórios", "📝 Registrar", "⚙️ Admin"])
        
        with tab1:
            if not df_oc.empty:
                f_st = st.selectbox("Visualizar:", ["Pendentes", "Arquivados", "Todos"])
                df_show = df_oc
                if f_st == "Pendentes": df_show = df_oc[df_oc['Status_Gestao'].fillna("Pendente").isin(["Pendente", ""])]
                elif f_st == "Arquivados": df_show = df_oc[df_oc['Status_Gestao'] == "Arquivado"]
                
                if df_show.empty: st.success("Tudo limpo!")
                for idx, row in df_show.iloc[::-1].iterrows():
                    cor = "#ffe6e6" if "Alta" in str(row.get('Acao_Sugerida')) else "#fff3cd"
                    enc_tag = '<div class="encaminhamento">🚶 ALUNO ENCAMINHADO</div>' if str(row.get('Encaminhado')) == "Sim" else ""
                    
                    with st.container():
                        st.markdown(f"""<div class="card" style="background:{cor}; border-left:5px solid orange">
                        <b>{row['Aluno']}</b> ({row['Turma']})<br><i>"{row['Descricao']}"</i>{enc_tag}</div>""", unsafe_allow_html=True)
                        
                        if st.session_state.id_intervencao_ativa == idx:
                            txt = st.text_area("Ação:", key=f"tx{idx}")
                            if st.button("Salvar", key=f"sv{idx}"):
                                atualizar_status_gestao(row['Aluno'], row['Data'], "Arquivado", txt)
                                st.session_state.pdf_buffer = gerar_pdf_continuo(pd.DataFrame([row.to_dict() | {'Intervencao': txt}]))
                                st.session_state.id_intervencao_ativa = None; st.rerun()
                        else:
                            if 'pdf_buffer' in st.session_state and st.session_state.pdf_buffer:
                                st.download_button("📥 PDF", st.session_state.pdf_buffer, "Ficha.pdf", "application/pdf")
                                if st.button("Fechar"): st.session_state.pdf_buffer = None; st.rerun()
                            elif st.session_state.id_intervencao_ativa is None:
                                if st.button("Intervir", key=f"b{idx}"): st.session_state.id_intervencao_ativa = idx; st.rerun()

        with tab2: 
            if not df_oc.empty: st.dataframe(df_oc)

        with tab3:
            st.header("🖨️ Relatórios PDF")
            if not df_oc.empty:
                mod = st.radio("Tipo:", ["Conselho de Classe (Turma)", "Individual (Aluno)"])
                ts = st.selectbox("Turma:", sorted(df_oc['Turma'].astype(str).unique()))
                dft = df_oc[df_oc['Turma'] == ts]
                
                if mod == "Individual (Aluno)":
                    al = st.selectbox("Aluno:", sorted(dft['Aluno'].unique()))
                    if st.button("Gerar Relatório"):
                        pdf = gerar_pdf_continuo(dft[dft['Aluno'] == al], f"HISTÓRICO: {al}")
                        st.download_button("📥 Baixar", pdf, "Rel_Aluno.pdf", "application/pdf")
                else:
                    if st.button("Gerar Relatório Conselho"):
                        pdf = gerar_pdf_conselho(dft, ts)
                        st.download_button("📥 Baixar Conselho", pdf, f"Conselho_{ts}.pdf", "application/pdf")

        with tab4:
            with st.form("new_reg", clear_on_submit=True):
                tg = st.selectbox("Turma", ["6A","6B","7A","7B","8A","8B","9A","9B"])
                ag = st.text_input("Aluno"); dg = st.text_area("Fato"); ig = st.text_area("Intervenção")
                if st.form_submit_button("Salvar"):
                    salvar_ocorrencia([ag], tg, "GESTÃO", dg, "Média", "Não", ig); st.success("Ok")

        with tab5:
            with st.form("new_usr", clear_on_submit=True):
                tp = st.selectbox("Tipo", ["Professor", "Gestor"])
                nm = st.text_input("Nome"); cd = st.text_input("Senha")
                if st.form_submit_button("Criar"): cadastrar_usuario(tp, nm, cd); st.success("Ok")
