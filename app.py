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
    modelo_ia = genai.GenerativeModel('gemini-pro')
except:
    st.error("Falta configurar a 'gemini_key' nos Secrets do Streamlit.")

# --- FUNÇÕES DE CONEXÃO ---
def conectar():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(st.secrets["service_account_info"]), scope)
    client = gspread.authorize(creds)
    return client.open("Dados_Escolares")

# --- FUNÇÕES DE BANCO DE DADOS ---
def carregar_dados(aba_nome):
    try:
        sheet = conectar().worksheet(aba_nome)
        dados = sheet.get_all_records()
        df = pd.DataFrame(dados)
        if df.empty:
            if aba_nome == "Alertas": return pd.DataFrame(columns=["Data", "Turma", "Professor", "Status"])
            elif "Página1" in aba_nome: return pd.DataFrame(columns=["Data", "Aluno", "Turma", "Professor", "Descricao", "Acao_Sugerida", "Intervencao", "Status_Gestao"])
            elif "Professores" in aba_nome: return pd.DataFrame(columns=["Nome", "Codigo"])
        return df
    except:
        return pd.DataFrame()

def salvar_ocorrencia(alunos, turma, prof, desc, acao, intervencao=""):
    sheet = conectar().sheet1
    data = datetime.now().strftime("%Y-%m-%d %H:%M")
    # Coluna H é o Status_Gestao, iniciamos como "Pendente"
    for aluno in alunos:
        sheet.append_row([data, aluno, turma, prof, desc, acao, intervencao, "Pendente"])

def atualizar_status_gestao(aluno, data, novo_status, intervencao_texto=None):
    wb = conectar()
    sheet = wb.sheet1
    # Busca a linha correta (Lógica simplificada: procura pelo aluno)
    # Em produção idealmente usaríamos IDs únicos, mas aqui procuramos a celula do aluno
    cell = sheet.find(aluno)
    if cell:
        # Status_Gestao é coluna 8 (H)
        sheet.update_cell(cell.row, 8, novo_status)
        if intervencao_texto:
            # Intervenção é coluna 7 (G)
            sheet.update_cell(cell.row, 7, intervencao_texto)

def excluir_ocorrencia(aluno, descricao_trecho):
    wb = conectar()
    sheet = wb.sheet1
    dados = sheet.get_all_records()
    # Procura a linha para deletar
    for i, row in enumerate(dados):
        # Compara Aluno e um pedaço da descrição para garantir
        if row['Aluno'] == aluno and descricao_trecho in row['Descricao']:
            sheet.delete_rows(i + 2) # +2 por causa do cabeçalho e indice 0
            break

def salvar_alerta(turma, prof):
    sheet = conectar().worksheet("Alertas")
    data = datetime.now().strftime("%H:%M")
    sheet.append_row([data, turma, prof, "Pendente"])

def atualizar_alerta_status(turma, novo_status):
    wb = conectar()
    sheet = wb.worksheet("Alertas")
    dados = sheet.get_all_records()
    for i, row in enumerate(dados):
        if row['Turma'] == turma and row['Status'] != "Resolvido":
            sheet.update_cell(i + 2, 4, novo_status)
            break

# --- CÉREBRO IA (VERSÃO FINAL - GEMINI PRO) ---
def consultar_ia(descricao, turma):
    prompt = f"""
    Atue como um coordenador pedagógico experiente. Analise a seguinte ocorrência escolar:
    Turma: {turma}
    Descrição: "{descricao}"
    
    Responda APENAS neste formato exato:
    GRAVIDADE: [Alta/Média/Baixa]
    AÇÃO: [Sua sugestão de intervenção curta e objetiva]
    """
    try:
        response = modelo_ia.generate_content(prompt)
        texto = response.text
        
        gravidade = "Média"
        acao = texto
        if "GRAVIDADE:" in texto:
            partes = texto.split("AÇÃO:")
            gravidade = partes[0].replace("GRAVIDADE:", "").strip()
            acao = partes[1].strip() if len(partes) > 1 else texto
        return gravidade, acao
        
    except Exception as e:
        # Em caso de erro, devolve algo seguro para não travar o sistema
        return "Análise Pendente", "Não foi possível contatar a IA. Verifique a conexão."
        
# --- ESTADOS DA SESSÃO ---
if 'prof_logado' not in st.session_state: st.session_state.prof_logado = False
if 'prof_nome' not in st.session_state: st.session_state.prof_nome = ""
if 'lista_alunos' not in st.session_state: st.session_state.lista_alunos = []
if 'aba_ativa_gestao' not in st.session_state: st.session_state.aba_ativa_gestao = "🔥 Em Tempo Real"

# --- INTERFACE ---
st.title("🏫 Sistema Escolar Inteligente")

menu = st.sidebar.radio("Menu", ["Acesso Professor", "Painel Gestão"])

# ==========================================
# ÁREA DO PROFESSOR
# ==========================================
if menu == "Acesso Professor":
    
    # LOGIN PERSISTENTE
    if not st.session_state.prof_logado:
        with st.expander("🔐 Login do Professor", expanded=True):
            login_nome = st.text_input("Nome")
            login_codigo = st.text_input("Código", type="password")
            if st.button("Entrar"):
                df = carregar_dados("Professores")
                if not df.empty:
                    df['Codigo'] = df['Codigo'].astype(str)
                    if not df[(df['Nome'] == login_nome) & (df['Codigo'] == login_codigo)].empty:
                        st.session_state.prof_logado = True
                        st.session_state.prof_nome = login_nome
                        st.rerun()
                    else:
                        st.error("Dados incorretos.")
    else:
        # PROFESSOR LOGADO
        prof_nome = st.session_state.prof_nome
        col_top1, col_top2 = st.columns([4, 1])
        col_top1.success(f"Logado como: **{prof_nome}**")
        if col_top2.button("Sair"):
            st.session_state.prof_logado = False
            st.rerun()

        # --- BOTÃO DE PÂNICO ---
        st.markdown("---")
        col_p1, col_p2 = st.columns([3, 1])
        col_p1.write("### 🚨 Ajuda Imediata")
        if col_p2.button("CHAMAR GESTÃO", type="primary"):
            st.session_state.panico_mode = True
        
        if st.session_state.get('panico_mode'):
            with st.form("panico_form"):
                st.warning("Isso enviará um alerta vermelho para a coordenação.")
                t_panico = st.selectbox("Sala Atual:", ["6A", "6B", "7A", "7B", "8A", "8B", "9A", "9B"])
                if st.form_submit_button("CONFIRMAR ALERTA"):
                    salvar_alerta(t_panico, prof_nome)
                    st.success("Alerta enviado! A gestão está a caminho.")
                    time.sleep(2)
                    st.session_state.panico_mode = False
                    st.rerun()

        # --- FORMULÁRIO DE OCORRÊNCIA ---
        st.markdown("---")
        st.subheader("📝 Nova Ocorrência")
        
        turma = st.selectbox("Turma", ["6A", "6B", "7A", "7B", "8A", "8B", "9A", "9B"])
        
        c1, c2 = st.columns([3, 1])
        novo_aluno = c1.text_input("Nome do Aluno")
        if c2.button("➕ Adicionar"):
            if novo_aluno: st.session_state.lista_alunos.append(novo_aluno)
        
        if st.session_state.lista_alunos:
            st.info(f"Alunos: {', '.join(st.session_state.lista_alunos)}")
            if st.button("Limpar Lista"):
                st.session_state.lista_alunos = []
                st.rerun()

        descricao = st.text_area("Descrição")
        
        if st.button("Analisar com IA e Salvar"):
            if st.session_state.lista_alunos and descricao:
                with st.spinner("A Inteligência Artificial está analisando o caso..."):
                    gravidade, acao = consultar_ia(descricao, turma)
                    salvar_ocorrencia(st.session_state.lista_alunos, turma, prof_nome, descricao, acao)
                
                st.success(f"Salvo! IA Classificou como: {gravidade}")
                # Limpa apenas o formulário, mantém o login
                st.session_state.lista_alunos = []
                time.sleep(2)
                st.rerun()
            else:
                st.warning("Preencha todos os campos.")

# ==========================================
# ÁREA DA GESTÃO
# ==========================================
elif menu == "Painel Gestão":
    st_autorefresh(interval=10000, key="gestaorefresh")
    
    # POP UP DE ALERTA
    df_alertas = carregar_dados("Alertas")
    if not df_alertas.empty:
        pendentes = df_alertas[df_alertas['Status'].isin(["Pendente", "Em Atendimento"])]
        for i, row in pendentes.iterrows():
            st.error(f"🚨 ALERTA: Sala {row['Turma']} - Prof. {row['Professor']} ({row['Data']})")
            c1, c2 = st.columns(2)
            if row['Status'] == "Pendente":
                if c1.button("👀 Estou vendo", key=f"ver_{i}"):
                    atualizar_alerta_status(row['Turma'], "Em Atendimento")
                    st.rerun()
            else:
                # Se já está em atendimento
                if c1.button("✅ Resolvido (Sem registro)", key=f"ok_{i}"):
                    atualizar_alerta_status(row['Turma'], "Resolvido")
                    st.rerun()
                if c2.button("📝 Resolver e Registrar", key=f"reg_{i}"):
                    # Redireciona para aba de registro e preenche dados
                    st.session_state.aba_ativa_gestao = "📝 Registrar Direto"
                    st.session_state.dados_panico = {"turma": row['Turma'], "prof": row['Professor']}
                    # NÃO marcamos como resolvido ainda, só depois de salvar o form
                    st.rerun()

    # ABAS DE NAVEGAÇÃO (Controladas por variavel para permitir redirecionamento)
    tab1, tab2, tab3, tab4 = st.tabs(["🔥 Em Tempo Real", "📝 Registrar Direto", "🏫 Por Sala", "⚙️ Admin"])
    
    # ABA TEMPO REAL
    with tab1:
        st.header("Ocorrências Pendentes")
        df = carregar_dados("Página1")
        
        if not df.empty and 'Status_Gestao' in df.columns:
            # Filtra apenas o que não foi arquivado ("Pendente" ou vazio)
            df_pendentes = df[df['Status_Gestao'] != "Arquivado"]
            
            if df_pendentes.empty:
                st.info("Tudo limpo! Nenhuma pendência.")
            
            for index, row in df_pendentes.iloc[::-1].iterrows():
                with st.container():
                    # Cor baseada na gravidade (Texto da IA)
                    cor = "#ffeeba" # Padrão Amarelo
                    if "Alta" in str(row['Acao_Sugerida']): cor = "#f8d7da" # Vermelho
                    elif "Baixa" in str(row['Acao_Sugerida']): cor = "#d4edda" # Verde
                    
                    st.markdown(f"""
                    <div style="background-color: {cor}; padding: 15px; border-radius: 10px; margin-bottom: 10px; border: 1px solid #ddd;">
                        <small>{row['Data']} | {row['Turma']}</small><br>
                        <strong>{row['Aluno']}</strong> (Prof: {row['Professor']})<br>
                        <p style="margin: 5px 0;"><i>"{row['Descricao']}"</i></p>
                        <b>🤖 IA:</b> {row['Acao_Sugerida']}
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # BOTÕES DE AÇÃO
                    c_ok, c_interv, c_exc = st.columns([1, 2, 1])
                    
                    # 1. Botão OK (Arquiva)
                    if c_ok.button("✅ Ok / Visto", key=f"btn_ok_{index}"):
                        atualizar_status_gestao(row['Aluno'], row['Data'], "Arquivado")
                        st.rerun()
                        
                    # 2. Botão Registrar Intervenção
                    with c_interv.popover("✍️ Registrar Intervenção"):
                        txt_interv = st.text_area("O que foi feito?", key=f"text_{index}")
                        if st.button("Salvar e Arquivar", key=f"save_{index}"):
                            atualizar_status_gestao(row['Aluno'], row['Data'], "Arquivado", txt_interv)
                            st.success("Intervenção salva!")
                            time.sleep(1)
                            st.rerun()
                            
                    # 3. Botão Excluir
                    if c_exc.button("🗑️ Excluir", key=f"del_{index}"):
                        excluir_ocorrencia(row['Aluno'], row['Descricao'][:10]) # Usa parte da descriçao para identificar
                        st.warning("Registro excluído.")
                        time.sleep(1)
                        st.rerun()

    # ABA REGISTRAR DIRETO
    with tab2:
        # Se veio do botão de pânico, preenche automático
        dados_pre = st.session_state.get('dados_panico', {})
        turma_def = dados_pre.get('turma', "6A")
        
        if dados_pre:
            st.info(f"📝 Registrando ocorrência do chamado da sala {turma_def}")

        t_gestao = st.selectbox("Turma", ["6A", "6B", "7A", "7B", "8A", "8B", "9A", "9B"], index=["6A", "6B", "7A", "7B", "8A", "8B", "9A", "9B"].index(turma_def) if turma_def in ["6A", "6B"] else 0)
        
        aluno_g = st.text_input("Nome do Aluno (Gestão)")
        desc_g = st.text_area("Descrição")
        interv_g = st.text_area("Intervenção já realizada")
        
        if st.button("Registrar Caso"):
            # 1. Salva a ocorrencia
            grav, acao = consultar_ia(desc_g, t_gestao)
            salvar_ocorrencia([aluno_g], t_gestao, "GESTÃO", desc_g, acao, interv_g)
            
            # 2. Se tinha um alerta de pânico pendente, marca como resolvido agora
            if dados_pre:
                atualizar_alerta_status(turma_def, "Resolvido")
                del st.session_state['dados_panico']
            
            st.success("Caso registrado e alerta baixado!")
            time.sleep(2)
            st.rerun()

    # OUTRAS ABAS (Por Sala e Admin) mantêm-se similares ou simplificadas para foco
    with tab3:
        df = carregar_dados("Página1")
        if not df.empty:
            turma_filtro = st.selectbox("Filtrar Turma", df['Turma'].unique())
            st.dataframe(df[df['Turma'] == turma_filtro])

    with tab4:
        st.write("Cadastro de Professores")
        with st.form("novo_p"):
            n = st.text_input("Nome")
            c = st.text_input("Código")
            if st.form_submit_button("Salvar"):
                conectar().worksheet("Professores").append_row([n, c])
                st.success("Feito")

# Força a aba ativa se necessário (JavaScript hack)
if st.session_state.aba_ativa_gestao == "📝 Registrar Direto":
    # Isso é complexo de forçar visualmente sem componentes extras, 
    # mas a lógica de preenchimento acima (tab2) já trata os dados se o usuario clicar na aba.
    pass
