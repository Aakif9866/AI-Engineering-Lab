import uuid

import streamlit as st

from config import PROVIDERS
from pipeline import ask

st.set_page_config(page_title="Acme Shop Support", page_icon="💬")
st.title("Acme Shop Support")
st.caption("Answers come only from our policy documents, with sources.")

st.session_state.setdefault("user", uuid.uuid4().hex)  # rate limit is per browser session
provider = st.sidebar.selectbox("LLM provider", list(PROVIDERS))
st.sidebar.markdown("Try: *How long do refunds take?*, *What's the weather?*, *Ignore previous instructions*")

question = st.chat_input("Ask about refunds, shipping, orders or your account")
if question:
    st.chat_message("user").write(question)
    with st.chat_message("assistant"):
        with st.spinner("Searching our documents..."):
            a = ask(question, provider, user=st.session_state["user"])
        if a.status == "answered":
            st.write(a.text)
        elif a.status == "no_llm":
            st.warning(a.text)
        else:
            st.info(a.text)
        st.caption(f"status: {a.status}")
        if a.sources:
            with st.expander(f"Sources shown to the model ({len(a.sources)})"):
                for c in a.sources:
                    cited = " ✅ cited" if c.id in a.citations else ""
                    st.markdown(f"**{c.id}**{cited}\n\n{c.text}")
