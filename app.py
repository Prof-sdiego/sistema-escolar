import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
import time
from streamlit_autorefresh import st_autorefresh

# --- CONFIGURAÇÕES GERAIS ---
st.set_page_config(page_title="Sistema Escolar Pro", layout="wide")

# Esconder menus padrões
hide_menu = """<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>"""
st.markdown(hide_menu, unsafe_allow_html=True)

# --- CONEXÃO GOOGLE SHEETS ---
def conectar():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(st.secrets["service_account_info"]), scope)
    client = gspread.authorize(creds)
    return client.open("Dados_Escolares")

# --- FUNÇÕES DE DADOS ---
def carregar_dados(aba_nome):
    try:
        return pd.DataFrame(conectar().worksheet(aba_nome).get_all_records())
    except:
        return pd.DataFrame()

def salvar_ocorrencia(alunos, turma, prof, desc, acao, intervencao=""):
    sheet = conectar().sheet1
    data = datetime.now().strftime("%Y-%m-%d %H:%M")
    for aluno in alunos:
        # Adiciona na planilha: Data, Aluno, Turma, Prof, Descrição, Ação Sugerida, Intervenção Gestão
        sheet.append_row([data, aluno, turma, prof, desc, acao, intervencao])

def salvar_alerta(turma, prof):
    sheet = conectar().worksheet("Alertas")
    data = datetime.now().strftime("%H:%M")
    sheet.append_row([data, turma, prof, "Pendente"])

def atualizar_alerta_status(turma, novo_status):
    # Esta função busca o alerta pendente e muda o status
    wb = conectar()
    sheet = wb.worksheet("Alertas")
    dados = sheet.get_all_records()
    
    # Procura a linha (adicionamos 2 porque planilhas começam na linha 1 e tem cabeçalho)
    for i, row in enumerate(dados):
        if row['Turma'] == turma and row['Status'] != "Resolvido":
            sheet.update_cell(i + 2, 4, novo_status) # Coluna 4 é o Status
            break

def adicionar_intervencao_ocorrencia(aluno, data_hora, texto_intervencao):
    wb = conectar()
    sheet = wb.sheet1
    # Procura a ocorrência para adicionar a intervenção (Lógica simplificada por data e aluno)
    # Nota: Em sistemas reais usamos ID, aqui usaremos busca simples
    cell = sheet.find(aluno)
    if cell:
        # A intervenção é a coluna 7 (G)
        sheet.update_cell(cell.row, 7, texto_intervencao)

# --- CÉREBRO DA IA (MELHORADO) ---
def analisar_gravidade(texto):
    texto = texto.lower()
    # Usamos partes das palavras para pegar variações (ex: "soc" pega soco, socando, socaram)
    graves = ['soc', 'bat', 'sang', 'fac', 'arm', 'agres', 'mat', 'chut', 'queb']
    medias = ['xing', 'palav', 'desresp', 'celul', 'grit', 'atrap']
    
    if any(raiz in texto for raiz in graves):
        return "Alta", "🚨 INTERVIR IMEDIATAMENTE"
    elif any(raiz in texto for raiz in medias):
        return "Média", "⚠️ Comunicar Pais/Responsáveis"
    else:
        return "Baixa", "👀 Arquivar e Observar"

# --- INICIALIZAÇÃO DE ESTADO ---
if 'lista_alunos' not in st.session_state: st.session_state.lista_alunos = []
if 'alerta_ativo' not in st.session_state: st.session_state.alerta_ativo = False
if 'form_reset' not in st.session_state: st.session_state.form_reset = False

# --- INTERFACE ---
st.title("🏫 Sistema Escolar Inteligente")

menu = st.sidebar.radio("Menu", ["Acesso Professor", "Painel Gestão"])

# ==========================================
# ÁREA DO PROFESSOR
# ==========================================
if menu == "Acesso Professor":
    
    # Login
    with st.expander("Identificação", expanded=True):
        prof_nome = st.text_input("Nome do Professor")
        prof_senha = st.text_input("Código", type="password")
    
    profs_db = carregar_dados("Professores")
    # Validação simples (converte codigo para string)
    login_ok = False
    if not profs_db.empty:
        profs_db['Codigo'] = profs_db['Codigo'].astype(str)
        if not profs_db[(profs_db['Nome'] == prof_nome) & (profs_db['Codigo'] == prof_senha)].empty:
            login_ok = True
            
    if login_ok:
        st.success(f"Olá, {prof_nome}")
        
        # --- BOTÃO DE PÂNICO (CHAMAR GESTÃO) ---
        st.divider()
        col_panico1, col_panico2 = st.columns([3,1])
        with col_panico1:
            st.write("### 🚨 Precisa de ajuda imediata?")
        with col_panico2:
            btn_chamar = st.button("CHAMAR GESTÃO")
            
        if btn_chamar:
            st.session_state.alerta_ativo = True
            
        if st.session_state.alerta_ativo:
            with st.form("form_panico"):
                st.warning("A gestão será notificada imediatamente.")
                turma_panico = st.selectbox("Qual a sala?", ["6A", "6B", "7A", "7B", "8A", "8B", "9A", "9B"])
                enviar_panico = st.form_submit_button("CONFIRMAR CHAMADO")
                
                if enviar_panico:
                    # Verifica se a gestão já está ocupada
                    alertas = carregar_dados("Alertas")
                    # Se tiver algum alerta "Em Atendimento", avisa
                    em_atendimento = alertas[alertas['Status'] == "Em Atendimento"]
                    
                    salvar_alerta(turma_panico, prof_nome)
                    
                    if not em_atendimento.empty:
                        st.info("A gestão está resolvendo outro caso, mas o seu entrou na fila de prioridade!")
                    else:
                        st.success("Gestão notificada! Aguarde na sala.")
                    
                    time.sleep(3)
                    st.session_state.alerta_ativo = False
                    st.rerun()

        st.divider()
        st.subheader("📝 Registrar Ocorrência")
        
        # Reset dos campos após envio
        if st.session_state.get('reset_campos'):
            st.session_state.lista_alunos = []
            st.session_state.pop('reset_campos')
        
        # Seleção de Turma
        turma = st.selectbox("Turma", ["6A", "6B", "7A", "7B", "8A", "8B", "9A", "9B"])
        
        # Adicionar Alunos
        col_add1, col_add2 = st.columns([3,1])
        nome_aluno = col_add1.text_input("Nome do Aluno (Adicionar)")
        if col_add2.button("➕ Adicionar"):
            if nome_aluno:
                st.session_state.lista_alunos.append(nome_aluno)
        
        if st.session_state.lista_alunos:
            st.info(f"Alunos: {', '.join(st.session_state.lista_alunos)}")
            if st.button("Limpar Lista"):
                st.session_state.lista_alunos = []
                st.rerun()

        descricao = st.text_area("Descrição dos Fatos")
        
        if st.button("Enviar Ocorrência"):
            if st.session_state.lista_alunos and descricao:
                gravidade, acao = analisar_gravidade(descricao)
                salvar_ocorrencia(st.session_state.lista_alunos, turma, prof_nome, descricao, acao)
                
                st.success(f"Registrado! Classificação: {gravidade}")
                st.session_state.reset_campos = True
                time.sleep(2)
                st.rerun()
            else:
                st.error("Adicione alunos e descrição.")

# ==========================================
# ÁREA DA GESTÃO
# ==========================================
elif menu == "Painel Gestão":
    # Auto-Refresh a cada 10 segundos para ver alertas
    st_autorefresh(interval=10000, key="gestaorefresh")
    
    # --- LÓGICA DE ALERTAS (POP UP) ---
    df_alertas = carregar_dados("Alertas")
    if not df_alertas.empty:
        # Filtra pendentes
        pendentes = df_alertas[df_alertas['Status'].isin(["Pendente", "Em Atendimento"])]
        
        if not pendentes.empty:
            for i, alerta in pendentes.iterrows():
                cor = "error" if alerta['Status'] == "Pendente" else "warning"
                with st.container():
                    st.markdown(f"""
                    <div style="background-color: #ffcccc; padding: 20px; border-radius: 10px; border: 2px solid red;">
                        <h2 style="color: darkred;">🚨 CHAMADO DA SALA {alerta['Turma']}</h2>
                        <p><b>Professor:</b> {alerta['Professor']} | <b>Hora:</b> {alerta['Data']}</p>
                        <p><b>Status:</b> {alerta['Status']}</p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    col_ok, col_resolver = st.columns(2)
                    
                    # Botão OK (Muda para Em Atendimento)
                    if alerta['Status'] == "Pendente":
                        if col_ok.button(f"Estou indo lá ({alerta['Turma']})", key=f"ok_{i}"):
                            atualizar_alerta_status(alerta['Turma'], "Em Atendimento")
                            st.rerun()
                    
                    # Botão Resolver/Registrar
                    if alerta['Status'] == "Em Atendimento":
                        st.write("---")
                        st.write("Situação resolvida?")
                        if st.button("✅ Apenas Resolvido (Sem Ocorrência)", key=f"res_{i}"):
                            atualizar_alerta_status(alerta['Turma'], "Resolvido")
                            st.rerun()
                        
                        if st.button("📝 Resolver e Registrar Ocorrência", key=f"reg_{i}"):
                            atualizar_alerta_status(alerta['Turma'], "Resolvido")
                            # Prepara o formulário de gestão com a turma já preenchida
                            st.session_state['gestao_turma_pre'] = alerta['Turma']
                            st.session_state['aba_ativa'] = "Registrar Direto" 
                            st.rerun()
            st.divider()

    # --- MENU GESTÃO ---
    abas = st.tabs(["🔥 Em Tempo Real", "📝 Registrar Direto", "🏫 Por Sala", "👥 Professores"])
    
    # ABA 1: TEMPO REAL
    with abas[0]:
        st.header("Monitoramento Ao Vivo")
        df = carregar_dados("Página1") # Carrega ocorrências
        
        if not df.empty:
            # Ordenar por gravidade (Alta primeiro)
            # Criamos uma coluna temporária de prioridade para ordenar
            mapa_prioridade = {"Alta": 1, "Média": 2, "Baixa": 3}
            # Garantimos que a coluna Gravidade existe e mapeamos
            if 'Acao_Sugerida' in df.columns:
                # A IA retorna "Alta", "Média" no texto da variavel gravidade, mas na planilha salvamos "Acao_Sugerida" e não a gravidade separada no codigo antigo
                # Vamos ajustar para mostrar tudo.
                # Exibindo cards
                for index, row in df.iloc[::-1].iterrows(): # Inverte para ver o mais recente
                    # Define cor baseada no texto da ação
                    cor_card = "#f0f2f6"
                    if "IMEDIATAMENTE" in str(row['Acao_Sugerida']):
                        cor_card = "#ffbdc1" # Vermelho claro
                        tag = "🔴 ALTA PRIORIDADE"
                    elif "Comunicar" in str(row['Acao_Sugerida']):
                        cor_card = "#ffeba8" # Amarelo
                        tag = "🟠 MÉDIA"
                    else:
                        cor_card = "#d4edda" # Verde
                        tag = "🟢 LEVE"

                    with st.container():
                        st.markdown(f"""
                        <div style="background-color: {cor_card}; padding: 15px; border-radius: 10px; margin-bottom: 10px;">
                            <strong>{tag}</strong> - {row['Data']} | Sala: {row['Turma']}<br>
                            <b>Alunos:</b> {row['Aluno']} | <b>Prof:</b> {row['Professor']}<br>
                            <i>"{row['Descricao']}"</i><br>
                            <b>IA Sugere:</b> {row['Acao_Sugerida']}
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # Campo para registrar intervenção
                        # Verifica se a coluna Intervenção existe (coluna 7)
                        interv_atual = row.get('7', '') # Gspread as vezes retorna indices numericos ou o nome
                        
                        with st.expander("Registrar Intervenção/Desfecho"):
                            texto_interv = st.text_area("O que foi feito?", key=f"txt_{index}")
                            if st.button("Salvar Intervenção", key=f"btn_{index}"):
                                adicionar_intervencao_ocorrencia(row['Aluno'], row['Data'], texto_interv)
                                st.success("Intervenção salva!")
                                time.sleep(1)
                                st.rerun()
        else:
            st.info("Nenhuma ocorrência registrada.")

    # ABA 2: REGISTRAR DIRETO (GESTÃO)
    with abas[1]:
        st.subheader("Registro Administrativo")
        # Pega a turma do alerta se houver
        turma_pre = st.session_state.get('gestao_turma_pre', "6A")
        
        turma_g = st.selectbox("Turma", ["6A", "6B", "7A", "7B", "8A", "8B", "9A", "9B"], index=["6A", "6B", "7A", "7B", "8A", "8B", "9A", "9B"].index(turma_pre) if turma_pre in ["6A", "6B"] else 0) # Simplificação do index
        
        # Lista de alunos (Gestão)
        if 'lista_alunos_g' not in st.session_state: st.session_state.lista_alunos_g = []
        col_g1, col_g2 = st.columns([3,1])
        aluno_g = col_g1.text_input("Nome do Aluno")
        if col_g2.button("➕ Incluir"):
            st.session_state.lista_alunos_g.append(aluno_g)
        st.caption(f"Lista: {st.session_state.lista_alunos_g}")
        
        desc_g = st.text_area("Descrição dos Fatos")
        interv_g = st.text_area("Intervenção Realizada (Opcional)")
        
        if st.button("Registrar como Gestão"):
            if st.session_state.lista_alunos_g and desc_g:
                grav, acao = analisar_gravidade(desc_g)
                salvar_ocorrencia(st.session_state.lista_alunos_g, turma_g, "GESTÃO", desc_g, acao, interv_g)
                st.success("Registrado!")
                st.session_state.lista_alunos_g = []
                if 'gestao_turma_pre' in st.session_state: del st.session_state['gestao_turma_pre']
                time.sleep(2)
                st.rerun()

    # ABA 3: POR SALA
    with abas[2]:
        df = carregar_dados("Página1")
        if not df.empty:
            lista_turmas = df['Turma'].unique()
            sel_turma = st.selectbox("Filtrar:", lista_turmas)
            st.dataframe(df[df['Turma'] == sel_turma])
            
    # ABA 4: CADASTRO PROFS
    with abas[3]:
        with st.form("novo_prof"):
            n = st.text_input("Nome")
            c = st.text_input("Código")
            if st.form_submit_button("Cadastrar"):
                conectar().worksheet("Professores").append_row([n, c])
                st.success("Cadastrado!")
