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

# --- CONFIGURAÇÕES GERAIS ---
st.set_page_config(page_title="Ocorrência Digital", layout="wide", page_icon="🏫")

# CSS
st.markdown("""
<style>
    #MainMenu {visibility: hidden;} 
    footer {visibility: hidden;} 
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# --- SOM ---
def gerenciar_som(tipo="normal", chave_evento=None):
    if 'sons_tocados' not in st.session_state: st.session_state.sons_tocados = set()
    if chave_evento in st.session_state.sons_tocados: return

    sound_url = "https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"
    if tipo == "grave": sound_url = "https://assets.mixkit.co/active_storage/sfx/995/995-preview.mp3"
    
    st.markdown(f"""<audio autoplay><source src="{sound_url}" type="audio/mp3"></audio>""", unsafe_allow_html=True)
    if chave_evento: st.session_state.sons_tocados.add(chave_evento)

# --- GERADOR DE PDF (PROFISSIONAL E EM LOTE) ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, 'OCORRÊNCIA DIGITAL - RELATÓRIO ESCOLAR', 0, 1, 'C')
        self.ln(5)
        self.line(10, 25, 200, 25)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def desenhar_pagina_ocorrencia(pdf, dados):
    """Desenha o conteúdo de UMA ocorrência na página atual do PDF"""
    def limpa(texto):
        return str(texto).encode('latin-1', 'replace').decode('latin-1')

    pdf.set_font("Arial", size=12)
    
    # Dados do Cabeçalho
    pdf.set_font("Arial", 'B', 12); pdf.cell(30, 10, "Aluno:", 0, 0)
    pdf.set_font("Arial", '', 12); pdf.cell(100, 10, limpa(dados['Aluno']), 0, 0)
    
    pdf.set_font("Arial", 'B', 12); pdf.cell(20, 10, "Turma:", 0, 0)
    pdf.set_font("Arial", '', 12); pdf.cell(0, 10, limpa(dados['Turma']), 0, 1)
    
    pdf.set_font("Arial", 'B', 12); pdf.cell(30, 10, "Data:", 0, 0)
    pdf.set_font("Arial", '', 12); pdf.cell(0, 10, limpa(dados['Data']), 0, 1)
    
    pdf.set_font("Arial", 'B', 12); pdf.cell(30, 10, "Professor:", 0, 0)
    pdf.set_font("Arial", '', 12); pdf.cell(0, 10, limpa(dados['Professor']), 0, 1)
    
    pdf.ln(5); pdf.line(10, pdf.get_y(), 200, pdf.get_y()); pdf.ln(10)
    
    # Conteúdo
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, limpa("DESCRIÇÃO DOS FATOS:"), 0, 1)
    pdf.set_font("Arial", '', 11); pdf.multi_cell(0, 6, limpa(dados['Descricao']))
    pdf.ln(10)
    
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, limpa("INTERVENÇÃO DA GESTÃO:"), 0, 1)
    pdf.set_font("Arial", '', 11)
    interv = dados.get('Intervencao', '') or "Sem registro."
    pdf.multi_cell(0, 6, limpa(interv))
    
    # Assinaturas (Sempre no final da página)
    pdf.set_y(-50) 
    pdf.set_font("Arial", '', 10)
    y = pdf.get_y()
    
    pdf.line(20, y, 80, y); pdf.line(110, y, 190, y)
    pdf.text(35, y + 5, limpa("Aluno(a)")); pdf.text(135, y + 5, limpa("Responsável"))
    
    pdf.line(65, y + 25, 145, y + 25)
    pdf.text(90, y + 30, limpa("Gestão Escolar"))

def gerar_pdf_lote(dataframe_filtrado):
    """Gera um único PDF com várias páginas (uma por ocorrência)"""
    pdf = PDF()
    for index, row in dataframe_filtrado.iterrows():
        pdf.add_page()
        desenhar_pagina_ocorrencia(pdf, row.to_dict())
    return pdf.output(dest='S').encode('latin-1')

# --- CONEXÃO ---
@st.cache_resource
def conectar():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(st.secrets["service_account_info"]), scope)
    client = gspread.authorize(creds)
    return client.open("Dados_Escolares")

# --- IA (AUTO-DETECÇÃO) ---
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

# --- IA ---
def consultar_ia(descricao, turma):
    if not nome_modelo_ativo: return "Erro Config", "IA Indisponível"
    prompt = f"""
    Especialista CONVIVA SP (Protocolo 179).
    Dados: Turma {turma} | Fato: "{descricao}"
    Classifique GRAVIDADE: ALTA, MÉDIA, BAIXA.
    Sugira AÇÃO mediação. Responda: GRAVIDADE: [G] AÇÃO: [A]
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

# --- ESTADOS ---
if 'panico_mode' not in st.session_state: st.session_state.panico_mode = False
if 'id_intervencao_ativa' not in st.session_state: st.session_state.id_intervencao_ativa = None
if 'total_ocorrencias' not in st.session_state: st.session_state.total_ocorrencias = 0
if 'pdf_buffer' not in st.session_state: st.session_state.pdf_buffer = None

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
            st.write("### 🔐 Acesso Professor")
            ln = st.text_input("Nome"); lc = st.text_input("Código", type="password")
            if st.form_submit_button("Entrar"):
                df = carregar_professores()
                if not df.empty:
                    df['Codigo'] = df['Codigo'].astype(str)
                    if not df[(df['Nome'] == ln) & (df['Codigo'] == lc)].empty:
                        st.session_state.prof_logado = True; st.session_state.prof_nome = ln
                        st.query_params["prof_logado"] = "true"; st.query_params["prof_nome"] = ln; st.rerun()
                    else: st.error("Dados inválidos.")
    else:
        col_h1, col_h2 = st.columns([4,1])
        col_h1.success(f"👤 Prof. **{st.session_state.prof_nome}**")
        if col_h2.button("Sair"): st.session_state.prof_logado = False; st.query_params.clear(); st.rerun()

        tab_reg, tab_hist = st.tabs(["📝 Nova Ocorrência", "🗂️ Meus Registros"])

        with tab_reg:
            c1, c2 = st.columns([3,1])
            c1.warning("⚠️ Apenas para **Emergências Graves**.")
            if c2.button("🚨 CHAMAR GESTÃO", type="primary"): st.session_state.panico_mode = True
            
            if st.session_state.panico_mode:
                with st.form("panico"):
                    st.error("CONFIRMAR EMERGÊNCIA?")
                    t = st.selectbox("Sala:", ["6A","6B","7A","7B","8A","8B","9A","9B"])
                    if st.form_submit_button("CONFIRMAR"):
                        salvar_alerta(t, st.session_state.prof_nome)
                        st.toast("🚨 Alerta enviado!", icon="🚨"); time.sleep(2); st.session_state.panico_mode = False; st.rerun()
                    if st.form_submit_button("Cancelar"): st.session_state.panico_mode = False; st.rerun()
            
            st.markdown("---")
            with st.form("form_oc", clear_on_submit=True):
                st.subheader("Registro de Fatos")
                turma = st.selectbox("Turma", ["6A","6B","7A","7B","8A","8B","9A","9B"])
                alunos_texto = st.text_area("Alunos (separe por vírgula ou Enter)", placeholder="Ex: João Silva, Maria Souza")
                descricao = st.text_area("Descrição do Ocorrido", height=150)
                if st.form_submit_button("Enviar Ocorrência"):
                    if alunos_texto and descricao:
                        raw_names = alunos_texto.replace("\n", ",").replace(";", ",")
                        lista_alunos = [n.strip() for n in raw_names.split(",") if n.strip()]
                        st.toast("✅ Enviado!", icon="🚀")
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
                        if row['Status_Gestao'] == "Arquivado": st.success(f"**Gestão:** {row.get('Intervencao', '')}")

# ================= GESTÃO =================
elif menu == "Painel Gestão":
    if not st.session_state.gestao_logada:
        with st.form("login_gestao"):
            st.write("### 📊 Acesso Gestão")
            gn = st.text_input("Usuário"); gc = st.text_input("Senha", type="password")
            if st.form_submit_button("Acessar Painel"):
                df_g = carregar_gestores()
                login_ok = False
                if not df_g.empty:
                    df_g['Codigo'] = df_g['Codigo'].astype(str)
                    if not df_g[(df_g['Nome'] == gn) & (df_g['Codigo'] == gc)].empty: login_ok = True
                if login_ok:
                    st.session_state.gestao_logada = True; st.session_state.gestao_nome = gn
                    st.query_params["gestao_logada"] = "true"; st.query_params["gestao_nome"] = gn; st.rerun()
                else: st.error("Acesso negado.")
    else:
        col_g1, col_g2 = st.columns([4,1])
        col_g1.info(f"📊 Gestor: **{st.session_state.gestao_nome}**")
        if col_g2.button("Sair", key="sair_gest"):
            st.session_state.gestao_logada = False; st.query_params.clear(); st.rerun()

        if st.session_state.id_intervencao_ativa is None: st_autorefresh(interval=15000, key="gestaorefresh")
        else: st.info("⏸️ Atualização pausada para edição.")

        df_alertas = carregar_alertas()
        if not df_alertas.empty:
            pendentes = df_alertas[df_alertas['Status'].isin(["Pendente", "Em Atendimento"])]
            for i, row in pendentes.iterrows():
                st.error(f"🚨 URGENTE: Sala {row['Turma']} ({row['Professor']})")
                if row['Status'] == "Pendente": gerenciar_som("grave", f"alert_{row['Data']}_{row['Turma']}")
                c1, c2 = st.columns(2)
                if row['Status'] == "Pendente":
                    if c1.button("👀 A Caminho", key=f"v{i}"): atualizar_alerta_status(row['Turma'], "Em Atendimento"); st.rerun()
                else:
                    if c1.button("✅ Resolvido", key=f"k{i}"): atualizar_alerta_status(row['Turma'], "Resolvido"); st.rerun()
                    if c2.button("📝 Registrar", key=f"r{i}"):
                        st.session_state.dados_panico = {"turma": row['Turma'], "prof": row['Professor']}
                        st.session_state.aba_ativa_gestao = "reg"; st.rerun()

        tab1, tab2, tab3, tab4, tab5 = st.tabs(["🔥 Tempo Real", "📝 Registrar", "🏫 Histórico", "🖨️ Relatórios", "⚙️ Admin"])
        
        with tab1:
            df_oc = carregar_ocorrencias_cache()
            qtd_atual = len(df_oc)
            if qtd_atual > st.session_state.total_ocorrencias:
                gerenciar_som("normal", f"novas_oc_{qtd_atual}")
                st.toast("🔔 Nova Ocorrência!", icon="📢"); st.session_state.total_ocorrencias = qtd_atual

            if not df_oc.empty and 'Status_Gestao' in df_oc.columns:
                contagem = df_oc['Aluno'].value_counts()
                pend = df_oc[df_oc['Status_Gestao'] != "Arquivado"]
                if pend.empty: st.success("Sem pendências.")
                
                for idx, row in pend.iloc[::-1].iterrows():
                    sugestao = str(row.get('Acao_Sugerida', ''))
                    cor, borda = "#fff3cd", "orange"
                    if "Alta" in sugestao: cor, borda = "#ffe6e6", "red"
                    elif "Baixa" in sugestao: cor, borda = "#e6fffa", "green"

                    qtd = contagem.get(row['Aluno'], 1)
                    aviso = f"<br>⚠️ <b>Atenção:</b> {qtd}ª ocorrência." if qtd > 1 else ""

                    with st.container():
                        st.markdown(f"""<div style='background:{cor};padding:15px;border-left:5px solid {borda};border-radius:5px;margin-bottom:10px'>
                        <div style="display:flex;justify-content:space-between;"><span><b>{row['Aluno']}</b> ({row['Turma']}) {aviso}</span><small>{row['Data']}</small></div>
                        <p style="margin:5px 0"><i>"{row['Descricao']}"</i></p><hr style="margin:5px 0;opacity:0.2"><small><b>🤖 IA:</b> {sugestao}</small></div>""", unsafe_allow_html=True)
                        
                        if st.session_state.id_intervencao_ativa == idx:
                            st.markdown(f"**Intervenção para {row['Aluno']}:**")
                            txt = st.text_area("Ação:", key=f"tx{idx}", height=100)
                            c_s, c_c = st.columns(2)
                            if c_s.button("💾 Salvar e Gerar PDF", key=f"sv{idx}"):
                                atualizar_status_gestao(row['Aluno'], row['Data'], "Arquivado", txt)
                                # Gera PDF Único
                                d_imp = row.to_dict(); d_imp['Intervencao'] = txt
                                st.session_state.pdf_buffer = gerar_pdf_lote(pd.DataFrame([d_imp]))
                                st.session_state.id_intervencao_ativa = None; st.rerun()
                            if c_c.button("Cancelar", key=f"can{idx}"): st.session_state.id_intervencao_ativa = None; st.rerun()
                        else:
                            if 'pdf_buffer' in st.session_state and st.session_state.pdf_buffer:
                                st.success("PDF Gerado!")
                                st.download_button("📥 Baixar PDF da Ocorrência", data=st.session_state.pdf_buffer, file_name="Ocorrencia.pdf", mime="application/pdf")
                                if st.button("Fechar"): st.session_state.pdf_buffer = None; st.rerun()
                            elif st.session_state.id_intervencao_ativa is None:
                                c1, c2, c3 = st.columns([1,3,1])
                                if c1.button("✅ Visto", key=f"ok{idx}"): atualizar_status_gestao(row['Aluno'], row['Data'], "Arquivado", "Visto"); st.rerun()
                                if c2.button("✍️ Intervir", key=f"bi{idx}"): st.session_state.id_intervencao_ativa = idx; st.rerun()
                                if c3.button("🗑️", key=f"d{idx}"): excluir_ocorrencia(row['Aluno'], row['Descricao'][:10]); st.rerun()

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
            tr = st.radio("Modo de Impressão:", ["Por Aluno (Individual)", "Turma Completa (Lote)"])
            if not df_oc.empty:
                ts = st.selectbox("Selecione a Turma:", sorted(df_oc['Turma'].astype(str).unique()), key="relt")
                dft = df_oc[df_oc['Turma'] == ts]
                
                if tr == "Por Aluno (Individual)":
                    al = st.selectbox("Selecione o Aluno:", sorted(dft['Aluno'].unique()))
                    if st.button("Gerar PDF do Aluno"):
                        df_aluno = dft[dft['Aluno'] == al]
                        pdf_bytes = gerar_pdf_lote(df_aluno)
                        st.download_button("📥 Baixar PDF Completo", data=pdf_bytes, file_name=f"Relatorio_{al}.pdf", mime="application/pdf")
                else:
                    if st.button(f"Gerar PDF da Turma ({len(dft)} ocorrências)"):
                        pdf_bytes = gerar_pdf_lote(dft)
                        st.download_button("📥 Baixar PDF da Turma", data=pdf_bytes, file_name=f"Relatorio_{ts}.pdf", mime="application/pdf")

        with tab5: # Admin
            st.write("### Cadastrar Usuários")
            c_adm1, c_adm2 = st.columns(2)
            with c_adm1:
                with st.form("new_prof"):
                    st.write("**Novo Professor**")
                    np = st.text_input("Nome"); cp = st.text_input("Senha")
                    if st.form_submit_button("Salvar Prof"): cadastrar_usuario("Professor", np, cp); st.success("Salvo!")
            with c_adm2:
                with st.form("new_gest"):
                    st.write("**Novo Gestor**")
                    ng = st.text_input("Nome"); cg = st.text_input("Senha")
                    if st.form_submit_button("Salvar Gestor"): cadastrar_usuario("Gestor", ng, cg); st.success("Salvo!")
