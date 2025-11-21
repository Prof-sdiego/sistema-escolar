import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
import time

# --- CONFIGURAÇÕES VISUAIS ---
st.set_page_config(page_title="Sistema Escolar Inteligente", layout="wide")

# Esconder Menu Técnico e Rodapé (CSS Hack)
hide_menu_style = """
        <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        </style>
        """
st.markdown(hide_menu_style, unsafe_allow_html=True)

# --- CONEXÃO COM GOOGLE SHEETS ---
def conectar_google():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(st.secrets["service_account_info"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    # Abre a planilha
    spreadsheet = client.open("Dados_Escolares")
    return spreadsheet

# --- FUNÇÕES DE DADOS ---
def carregar_ocorrencias():
    try:
        sheet = conectar_google().sheet1
        dados = sheet.get_all_records()
        return pd.DataFrame(dados)
    except:
        return pd.DataFrame()

def carregar_professores():
    try:
        # Tenta abrir a segunda aba chamada 'Professores'
        sheet = conectar_google().worksheet("Professores")
        dados = sheet.get_all_records()
        return pd.DataFrame(dados)
    except:
        return pd.DataFrame(columns=["Nome", "Codigo"])

def salvar_professor(nome, codigo):
    sheet = conectar_google().worksheet("Professores")
    sheet.append_row([nome, str(codigo)])

def salvar_ocorrencia(alunos_lista, turma, prof, descricao, sugestao_ia):
    sheet = conectar_google().sheet1
    data_atual = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Salva uma linha para cada aluno citado, mas com a mesma descrição
    for aluno in alunos_lista:
        sheet.append_row([data_atual, aluno, turma, prof, descricao, sugestao_ia])

# --- INTELIGÊNCIA ARTIFICIAL (Simulada/Regras) ---
def analisar_ocorrencia(descricao):
    """
    Analisa o texto para definir gravidade e ação.
    Procura palavras-chave.
    """
    desc_lower = descricao.lower()
    
    palavras_graves = ['bateu', 'soco', 'sangue', 'ameaça', 'droga', 'furto', 'agressão']
    palavras_medias = ['palavrão', 'xingou', 'desrespeito', 'celular', 'atrapalhou']
    
    if any(word in desc_lower for word in palavras_graves):
        return "🔴 Intervir Imediatamente (Grave)", "Alta"
    elif any(word in desc_lower for word in palavras_medias):
        return "🟠 Comunicar Pais (Média)", "Média"
    else:
        return "🟢 Arquivar/Observar (Leve)", "Baixa"

# --- INTERFACE DO SISTEMA ---

st.title("🏫 Sistema de Gestão Escolar")

# Menu Lateral de Navegação
menu = st.sidebar.radio("Navegação", ["Acesso Professor", "Painel Gestão"])

# --- ÁREA DO PROFESSOR ---
if menu == "Acesso Professor":
    st.header("📝 Registro de Ocorrências")
    
    # -- Autenticação Simples --
    with st.expander("🔐 Login do Professor", expanded=True):
        nome_prof = st.text_input("Seu Nome")
        codigo_prof = st.text_input("Código de Acesso", type="password")
    
    # Verifica Login
    df_profs = carregar_professores()
    login_valido = False
    
    if not df_profs.empty:
        # Converte código para string para garantir comparação
        df_profs['Codigo'] = df_profs['Codigo'].astype(str)
        if not df_profs[(df_profs['Nome'] == nome_prof) & (df_profs['Codigo'] == codigo_prof)].empty:
            login_valido = True

    if login_valido:
        st.success(f"Bem-vindo(a), {nome_prof}")
        
        with st.form("form_ocorrencia"):
            # Seleção de Turma
            lista_turmas = ["6ºA", "6ºB", "6ºC", "7ºA", "7ºB", "7ºC", "8ºA", "8ºB", "8ºC", "9ºA", "9ºB"]
            turma = st.selectbox("Selecione a Turma", lista_turmas)
            
            # Inserção Múltipla de Alunos
            st.write(" **Alunos envolvidos:**")
            col_input, col_btn = st.columns([3, 1])
            
            # Usamos session_state para guardar a lista de alunos enquanto o professor digita
            if 'lista_alunos' not in st.session_state:
                st.session_state.lista_alunos = []
                
            nome_aluno_input = st.text_input("Nome do Aluno (Adicione um por um)")
            if st.form_submit_button("➕ Adicionar Aluno à lista"):
                if nome_aluno_input:
                    st.session_state.lista_alunos.append(nome_aluno_input)
                    st.success(f"{nome_aluno_input} adicionado!")
            
            # Mostra quem já foi adicionado
            if st.session_state.lista_alunos:
                st.info(f"Alunos na ocorrência: {', '.join(st.session_state.lista_alunos)}")
            
            st.markdown("---")
            descricao = st.text_area("Descrição do Fato (Obrigatório)")
            
            # Botão Final
            btn_finalizar = st.form_submit_button("🚀 Enviar Ocorrência")
            
            if btn_finalizar:
                if len(st.session_state.lista_alunos) > 0 and descricao:
                    # 1. IA Analisa
                    acao_sugerida, gravidade = analisar_ocorrencia(descricao)
                    
                    # 2. Salva
                    salvar_ocorrencia(st.session_state.lista_alunos, turma, nome_prof, descricao, acao_sugerida)
                    
                    st.success("Ocorrência Registrada com Sucesso!")
                    # Limpa a lista
                    st.session_state.lista_alunos = []
                else:
                    st.error("Preencha a descrição e adicione pelo menos um aluno.")
                    
    elif codigo_prof: # Se digitou senha mas não validou
        st.error("Nome ou Código incorretos. Fale com a Gestão.")

# --- ÁREA DA GESTÃO ---
elif menu == "Painel Gestão":
    st.header("📊 Central de Inteligência e Controle")
    
    # Abas para organizar a gestão
    aba1, aba2, aba3 = st.tabs(["🏫 Por Sala", "🔍 Busca Aluno", "⚙️ Cadastrar Profs"])
    
    df = carregar_ocorrencias()
    
    with aba1:
        st.subheader("Visão por Sala")
        if not df.empty:
            turmas_ativas = df['Turma'].unique()
            turma_sel = st.selectbox("Filtrar Turma:", turmas_ativas)
            
            # Filtra dados da turma
            df_turma = df[df['Turma'] == turma_sel]
            
            # Agrupa por aluno para contar ocorrências
            contagem = df_turma['Aluno'].value_counts()
            
            col1, col2 = st.columns([1, 2])
            with col1:
                st.write("### Alunos com Ocorrências")
                # Tabela clicável (simulada com botões)
                for aluno, qtd in contagem.items():
                    if st.button(f"{aluno} ({qtd} ocorrências)"):
                        st.session_state['aluno_foco'] = aluno
            
            with col2:
                st.write("### Detalhes do Aluno")
                if 'aluno_foco' in st.session_state:
                    aluno_foco = st.session_state['aluno_foco']
                    historico = df_turma[df_turma['Aluno'] == aluno_foco]
                    
                    st.info(f"Mostrando histórico de: **{aluno_foco}**")
                    
                    for i, row in historico.iterrows():
                        with st.expander(f"{row['Data']} - Sugestão IA: {row['Acao_Sugerida']}"):
                            st.write(f"**Professor:** {row['Professor']}") # Assumindo coluna 4
                            st.write(f"**Fato:** {row['Descricao']}")
                            
                            # Botão Whats
                            msg = f"Olá, responsável pelo aluno {aluno_foco}. Precisamos conversar sobre: {row['Descricao']}"
                            link = f"https://wa.me/?text={msg}"
                            st.markdown(f"[📲 Chamar no WhatsApp]({link})", unsafe_allow_html=True)
        else:
            st.info("Sem dados ainda.")

    with aba2:
        st.subheader("Busca Rápida")
        busca = st.text_input("Digite o nome do aluno:")
        if busca and not df.empty:
            # Filtro inteligente (acha nomes parecidos)
            resultado = df[df['Aluno'].astype(str).str.contains(busca, case=False)]
            if not resultado.empty:
                st.dataframe(resultado[['Data', 'Aluno', 'Turma', 'Acao_Sugerida']])
            else:
                st.warning("Nenhum aluno encontrado.")

    with aba3:
        st.subheader("Cadastrar Novo Professor")
        with st.form("novo_prof"):
            novo_nome = st.text_input("Nome do Professor")
            novo_codigo = st.text_input("Criar Código de Acesso (Senha)")
            btn_criar = st.form_submit_button("Cadastrar")
            
            if btn_criar and novo_nome and novo_codigo:
                salvar_professor(novo_nome, novo_codigo)
                st.success(f"Professor {novo_nome} cadastrado com sucesso!")
