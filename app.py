import streamlit as st
import pandas as pd
from datetime import datetime
import os

# --- CONFIGURAÇÕES ---
st.set_page_config(page_title="Sistema Escolar", layout="wide")
ARQUIVO_DADOS = 'ocorrencias.csv'

# --- FUNÇÕES ---
def carregar_dados():
    if not os.path.exists(ARQUIVO_DADOS):
        return pd.DataFrame(columns=["Data", "Aluno", "Turma", "Gravidade", "Descricao", "Acao_Sugerida"])
    return pd.read_csv(ARQUIVO_DADOS)

def salvar_ocorrencia(aluno, turma, gravidade, descricao, acao_sugerida):
    df = carregar_dados()
    nova_linha = pd.DataFrame({
        "Data": [datetime.now().strftime("%Y-%m-%d %H:%M")],
        "Aluno": [aluno],
        "Turma": [turma],
        "Gravidade": [gravidade],
        "Descricao": [descricao],
        "Acao_Sugerida": [acao_sugerida]
    })
    df = pd.concat([df, nova_linha], ignore_index=True)
    df.to_csv(ARQUIVO_DADOS, index=False)
    return df

def cerebro_sistema(aluno, gravidade, turma):
    # IA Simples (Regras)
    df = carregar_dados()
    reincidencia = len(df[df['Aluno'] == aluno]) + 1
    
    sugestao = "Arquivar"
    if gravidade == "Alta":
        sugestao = "🚨 URGENTE: Reunião Presencial (Reincidência ou Gravidade Alta)"
    elif reincidencia >= 3:
        sugestao = f"⚠️ ALERTA: 3ª Ocorrência. Ligar para os pais."
    elif gravidade == "Média":
        sugestao = "📱 Enviar WhatsApp Informativo"
    
    return sugestao

# --- INTERFACE ---
st.title("🏫 Sistema de Gestão de Ocorrências")

# Menu Lateral
menu = st.sidebar.radio("Perfil de Acesso", ["Professor", "Direção/Gestão"])

if menu == "Professor":
    st.subheader("📝 Novo Registro")
    with st.form("form_oc"):
        aluno = st.text_input("Nome do Aluno")
        turma = st.selectbox("Turma", ["6A", "7B", "8A", "9C", "1EM"])
        gravidade = st.select_slider("Gravidade", options=["Baixa", "Média", "Alta"])
        desc = st.text_area("Descrição do Fato")
        
        enviar = st.form_submit_button("Registrar")
        
        if enviar and aluno and desc:
            sugestao = cerebro_sistema(aluno, gravidade, turma)
            salvar_ocorrencia(aluno, turma, gravidade, desc, sugestao)
            st.success(f"Registrado! Sugestão do Sistema: {sugestao}")

elif menu == "Direção/Gestão":
    st.subheader("📊 Painel de Controle")
    df = carregar_dados()
    
    if not df.empty:
        # Métricas
        total = len(df)
        graves = len(df[df['Gravidade'] == "Alta"])
        col1, col2 = st.columns(2)
        col1.metric("Total Ocorrências", total)
        col2.metric("Casos Graves", graves)
        
        st.divider()
        st.write("### Últimos Registros")
        st.dataframe(df.iloc[::-1], use_container_width=True)
        
        # Área de Ação
        st.write("### 📢 Ações Pendentes")
        for i, row in df.iloc[::-1].head(3).iterrows():
            if row['Gravidade'] in ['Média', 'Alta']:
                st.warning(f"Aluno: {row['Aluno']} | Sugestão: {row['Acao_Sugerida']}")
                link_whats = f"https://wa.me/?text=Sr(a).%20Responsável,%20gostaríamos%20de%20falar%20sobre%20o%20aluno%20{row['Aluno']}."
                st.link_button(f"Enviar Whats para Pais de {row['Aluno']}", link_whats)
    else:
        st.info("Nenhum dado registrado ainda.")
