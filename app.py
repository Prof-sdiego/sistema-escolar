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
st.set_page_config(page_title="Sistema Escolar AI", layout="wide")
hide_menu = """<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>"""
st.markdown(hide_menu, unsafe_allow_html=True)

# --- CONFIGURAÇÃO IA GEMINI ---
try:
    genai.configure(api_key=st.secrets["gemini_key"])
    # MUDANÇA AQUI: Usando o modelo mais recente e estável
    modelo_ia = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    st.error(f"Erro Config IA: {e}")
    modelo_ia = None

# --- CONEXÃO (CACHE RESOURCE) ---
@st.cache_resource
def conectar():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(st.secrets["service_account_info"]), scope)
    client = gspread.authorize(creds)
    return client.open("Dados_Escolares")

# --- LEITURA INTELIGENTE ---

def carregar_alertas(): 
    try:
        sheet = conectar().worksheet("Alertas")
        dados = sheet.get_all_records()
        if not dados: return pd.DataFrame(columns=["Data", "Turma", "Professor", "Status"])
        return pd.DataFrame(dados)
    except:
        return pd.DataFrame(columns=["Data", "Turma", "Professor", "Status"])

@st.cache_data(ttl=60) 
def carregar_ocorrencias_cache(): 
    try:
        sheet = conectar().sheet1
        dados = sheet.get_all_records()
        if not dados: return pd.DataFrame(columns=["Data", "Aluno", "Turma", "Professor", "Descricao", "Acao_Sugerida", "Intervencao", "Status_Gestao"])
        return pd.DataFrame(dados)
    except:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def carregar_professores(): 
    try:
        sheet = conectar().worksheet("Professores")
        dados = sheet.get_all_records()
        return pd.DataFrame(dados)
    except:
        return pd.DataFrame()

# --- ESCRITA (LIMPA CACHE) ---
def limpar_cache():
    st.cache_data.clear()

def salvar_ocorrencia(alunos, turma, prof, desc, acao, intervencao=""):
    try:
        sheet = conectar().sheet1
        data = datetime.now().strftime("%Y-%m-%d %H:%M")
        for aluno in alunos:
            sheet.append_row([data, aluno, turma, prof, desc, acao, intervencao, "Pendente"])
        limpar_cache()
        return True
    except Exception as e:
        st.error(f"Erro Salvar: {e}")
        return False

def atualizar_status_gestao(aluno, data, novo_status, intervencao_texto=None):
    wb = conectar()
    sheet = wb.sheet1
    try:
        cell = sheet.find(aluno)
        if cell:
            sheet.update_cell(cell.row, 8, novo_status)
            if intervencao_texto: sheet.update_cell(cell.row, 7, intervencao_texto)
        limpar_cache()
    except: pass

def excluir_ocorrencia(aluno, descricao_trecho):
    wb = conectar()
    sheet = wb.sheet1
    dados = sheet.get_all_records()
    for i, row in enumerate(dados):
        if row['Aluno'] == aluno and descricao_trecho in row['Descricao']:
            sheet.delete_rows(i + 2)
            break
    limpar_cache()

def salvar_alerta(turma, prof):
    conectar().worksheet("Alertas").append_row([datetime.now().strftime("%H:%M"), turma, prof, "Pendente"])

def atualizar_alerta_status(turma, novo_status):
    wb = conectar()
    sheet = wb.worksheet("Alertas")
    dados = sheet.get_all_records()
    for i, row in enumerate(dados):
        if row['Turma'] == turma and row['Status'] != "Resolvido":
            sheet.update_cell(i + 2, 4, novo_status)
            break

# --- IA (GEMINI 1.5 FLASH + SEGURANÇA LIBERADA) ---
def consultar_ia(descricao, turma):
    if modelo_ia is None: return "Erro Config", "IA Off"
    
    prompt = f"""Atue como coordenador pedagógico. Ocorrência: Turma {turma}, Descrição: "{descricao}".
    Responda formato exato: GRAVIDADE: [Alta/Média/Baixa] AÇÃO: [Sugestão curta]"""
    
    try:
        # Configurações para permitir conteúdo sobre violência escolar (necessário para gestão)
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
        
        response = modelo_ia.generate_content(prompt, safety_settings=safety_settings)
        texto = response.text
        
        grav, acao = "Média", texto
        if "GRAVIDADE:" in texto:
            partes = texto.split("AÇÃO:")
            grav = partes[0].replace("GRAVIDADE:", "").strip()
            acao = partes[1].strip() if len(partes) > 1 else texto
        return grav, acao
    except Exception as e:
        return "Erro IA", f"Detalhe: {e}"

# --- SESSÃO ---
if 'prof_logado' not in st.session_state: st.session_state.prof_logado = False
if 'prof_nome' not in st.session_state: st.session_state.prof_nome = ""
if 'lista_alunos' not in st.session_state: st.session_state.lista_alunos = []
if 'aba_ativa_gestao' not in st.session_state: st.session_state.aba_ativa_gestao = "🔥 Em Tempo Real"
if 'panico_mode' not in st.session_state: st.session_state.panico_mode = False

# --- INTERFACE ---
st.title("🏫 Sistema Escolar Inteligente")
menu = st.sidebar.radio("Menu", ["Acesso Professor", "Painel Gestão"])

# === PROFESSOR ===
if menu == "Acesso Professor":
    if not st.session_state.prof_logado:
        with st.expander("🔐 Login", expanded=True):
            ln = st.text_input("Nome")
            lc = st.text_input("Código", type="password")
            if st.button("Entrar"):
                df = carregar_professores()
                if not df.empty:
                    df['Codigo'] = df['Codigo'].astype(str)
                    if not df[(df['Nome'] == ln) & (df['Codigo'] == lc)].empty:
                        st.session_state.prof_logado = True
                        st.session_state.prof_nome = ln
                        st.rerun()
                    else: st.error("Erro login")
    else:
        st.success(f"Prof. **{st.session_state.prof_nome}**")
        if st.button("Sair"): 
            st.session_state.prof_logado = False
            st.rerun()
        
        st.divider()
        c1, c2 = st.columns([3,1])
        c1.write("### 🚨 EMERGÊNCIA")
        if c2.button("CHAMAR GESTÃO", type="primary"): st.session_state.panico_mode = True
        
        if st.session_state.panico_mode:
            with st.form("p"):
                st.warning("Enviando alerta vermelho para gestão.")
                t = st.selectbox("Sala", ["6A","6B","7A","7B","8A","8B","9A","9B"])
                if st.form_submit_button("CONFIRMAR"):
                    salvar_alerta(t, st.session_state.prof_nome)
                    st.success("Enviado!"); time.sleep(2)
                    st.session_state.panico_mode = False; st.rerun()
                if st.form_submit_button("Cancelar"):
                    st.session_state.panico_mode = False; st.rerun()

        st.divider()
        st.subheader("📝 Nova Ocorrência")
        t_oc = st.selectbox("Turma", ["6A","6B","7A","7B","8A","8B","9A","9B"])
        c1, c2 = st.columns([3,1])
        naluno = c1.text_input("Aluno")
        if c2.button("➕"): 
            if naluno: st.session_state.lista_alunos.append(naluno)
        if st.session_state.lista_alunos:
            st.info(f"Lista: {st.session_state.lista_alunos}")
            if st.button("Limpar"): st.session_state.lista_alunos = []; st.rerun()
        
        desc = st.text_area("Descrição")
        if st.button("🤖 Analisar e Salvar"):
            if st.session_state.lista_alunos and desc:
                with st.spinner("IA Analisando..."):
                    g, a = consultar_ia(desc, t_oc)
                    salvar_ocorrencia(st.session_state.lista_alunos, t_oc, st.session_state.prof_nome, desc, a)
                st.success(f"Salvo! Gravidade: {g}")
                st.session_state.lista_alunos = []; time.sleep(2); st.rerun()

# === GESTÃO ===
elif menu == "Painel Gestão":
    st_autorefresh(interval=15000, key="gestaorefresh")

    # ALERTAS
    df_alertas = carregar_alertas()
    if not df_alertas.empty:
        pendentes = df_alertas[df_alertas['Status'].isin(["Pendente", "Em Atendimento"])]
        for i, row in pendentes.iterrows():
            st.error(f"🚨 URGENTE: Sala {row['Turma']} ({row['Professor']})")
            c1, c2 = st.columns(2)
            if row['Status'] == "Pendente":
                if c1.button("👀 A Caminho", key=f"v{i}"): atualizar_alerta_status(row['Turma'], "Em Atendimento"); st.rerun()
            else:
                if c1.button("✅ Resolvido", key=f"k{i}"): atualizar_alerta_status(row['Turma'], "Resolvido"); st.rerun()
                if c2.button("📝 Registrar", key=f"r{i}"):
                    st.session_state.dados_panico = {"turma": row['Turma'], "prof": row['Professor']}
                    st.session_state.aba_ativa_gestao = "reg"
                    st.rerun()

    # ABAS
    tab1, tab2, tab3, tab4 = st.tabs(["🔥 Tempo Real", "📝 Registrar", "🏫 Histórico", "⚙️ Admin"])
    
    with tab1:
        df = carregar_ocorrencias_cache()
        if not df.empty and 'Status_Gestao' in df.columns:
            pend = df[df['Status_Gestao'] != "Arquivado"]
            if pend.empty: st.success("Sem pendências.")
            for idx, row in pend.iloc[::-1].iterrows():
                cor = "#fff3cd"
                if "Alta" in str(row.get('Acao_Sugerida')): cor = "#f8d7da"
                elif "Baixa" in str(row.get('Acao_Sugerida')): cor = "#d4edda"
                
                with st.container():
                    st.markdown(f"""<div style='background:{cor};padding:15px;border-radius:10px;margin-bottom:10px'>
                    <b>{row['Aluno']}</b> ({row['Turma']})<br><i>"{row['Descricao']}"</i><br>
                    <small>IA: {row.get('Acao_Sugerida')}</small></div>""", unsafe_allow_html=True)
                    
                    c1, c2, c3 = st.columns([1,2,1])
                    if c1.button("✅ Ok", key=f"ok{idx}"): atualizar_status_gestao(row['Aluno'], row['Data'], "Arquivado"); st.rerun()
                    with c2.popover("Intervenção"):
                        txt = st.text_area("Ação", key=f"tx{idx}")
                        if st.button("Salvar", key=f"sv{idx}"): atualizar_status_gestao(row['Aluno'], row['Data'], "Arquivado", txt); st.rerun()
                    if c3.button("🗑️", key=f"d{idx}"): excluir_ocorrencia(row['Aluno'], row['Descricao'][:10]); st.rerun()

    with tab2: # Registrar Direto
        dpre = st.session_state.get('dados_panico', {})
        turma_ini = dpre.get('turma', "6A")
        if dpre: st.info(f"Resolvendo chamado da {turma_ini}")
        
        tg = st.selectbox("Turma", ["6A","6B","7A","7B","8A","8B","9A","9B"], index=["6A","6B","7A","7B","8A","8B","9A","9B"].index(turma_ini) if turma_ini in ["6A","6B","7A","7B","8A","8B","9A","9B"] else 0)
        ag = st.text_input("Aluno"); dg = st.text_area("Fato"); ig = st.text_area("Intervenção")
        if st.button("Registrar"):
            g, a = consultar_ia(dg, tg)
            salvar_ocorrencia([ag], tg, "GESTÃO", dg, a, ig)
            if dpre: atualizar_alerta_status(turma_ini, "Resolvido"); del st.session_state['dados_panico']
            st.success("Feito!"); time.sleep(2); st.rerun()

    with tab3:
        df = carregar_ocorrencias_cache()
        if not df.empty:
            t = st.selectbox("Ver Turma:", sorted(df['Turma'].astype(str).unique()))
            st.dataframe(df[df['Turma'] == t])
            
    with tab4:
        with st.form("np"):
            if st.form_submit_button("Cadastrar Prof"):
                conectar().worksheet("Professores").append_row([st.text_input("Nome"), st.text_input("Senha")])
                st.success("Ok")
