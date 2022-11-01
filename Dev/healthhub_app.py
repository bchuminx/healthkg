import json
import spacy
import spacy_dbpedia_spotlight
import spacy_streamlit
import streamlit as st
import pandas as pd
import numpy as np

from neo4j import GraphDatabase

uri = "bolt://localhost:7687"
driver = GraphDatabase.driver(uri, auth=("neo4j", "ben27981"))

nlp = spacy.load('en_core_web_lg')
nlp.add_pipe('dbpedia_spotlight')

st.set_page_config(
    page_title="Health Knowledge Hub",
    layout='wide'
)

def get_similar(entity):
    with driver.session() as session:
        query = """
                match (n)-[:related_to]-(x)
                where (n.type = 'Disease' or n.type = 'Condition') and n.name =~ '(?i)""" + entity + """' and n.text <> ""
                return distinct x.name as Most_Similar
                """
    return session.run(query)

def get_definition(entity):
    with driver.session() as session:
        query = """
                match (n)
                where (n.type = 'Disease' or n.type = 'Condition') and n.name =~ '(?i)""" + entity + """' and n.text <> ""
                return distinct n.text as Definition, n.source as Source
                """
    return session.run(query)

def get_answer(entity, type):
    type = type.title()
    with driver.session() as session:
        query = """
                match (n)-[r]-(x)
                where n.type =~ '(?i)"""+type+"""' and r.name =~ '(?i)""" + entity + """' and not x.name =~ '(?i)""" + entity + """'
                return distinct x.type as Class,  x.name as """+type+""", r.source as Source, r.text as Notes
                """
    return session.run(query)

def get_info(entity):
    with driver.session() as session:
        query = """
                match (n:Info)-[r]-(x)
                where r.name =~ '(?i)""" + entity + """'
                return distinct r.text as Info, r.source as Source
                """
    return session.run(query)
    
st.title('Health Knowledge Hub')

query = st.text_input('Type to search', '')


search_type = ''
results = None

hide_table_row_index = """
            <style>
            thead tr th:first-child {display:none}
            tbody th {display:none}
            </style>
            """

st.markdown(hide_table_row_index, unsafe_allow_html=True)

col1, col2 = st.columns([3,2])

if query != '':
    answer, most_similar, definition, info = None, None, None, None
    search_types = []

    doc = nlp(query)
    
    for token in doc:
        #print(token.text, token.lemma_, token.pos_, token.tag_, token.dep_, token.shape_, token.is_alpha, token.is_stop)
        if token.dep_ in ['nsubj', 'conj', 'ROOT', 'dobj'] and token.pos_ == 'NOUN':
            if token.lemma_ in ['medication', 'medicine', 'treatment']:
                search_type = 'prescription'
            elif token.lemma_ == 'management':
                search_type = 'management'
            elif token.lemma_ == 'screening':
                search_type = 'checkup'
            elif token.lemma_ in ['bill', 'payment', 'subsidy']:
                search_type = 'expenses'
            else:
                search_type=token.lemma_
            if search_type != "":
                search_types.append(search_type)
        elif (token.dep_ in ['ROOT', 'conj'] or token.dep_ == 'relcl' or token.dep_ in ['ccomp', 'xcomp'])  and token.pos_ == 'VERB':
            if token.lemma_ in ['avoid', 'manage', 'prevent']:
                search_type='management'
            elif token.lemma_ in ['cure', 'medicate', 'treat']:
                search_type = 'prescription'
            elif token.lemma_ in ['cause', 'risk']:
                search_type = 'riskfactor'
            elif token.lemma_ in ['check', 'detect', 'test']:
                search_type = 'test'
            elif token.lemma_ in ['screen']:
                search_type = 'checkup'
            elif token.lemma_ in ['expense', 'subsidise', 'subsidize', 'pay']:
                search_type = 'expenses'
            else:
                search_type=token.lemma_
            if search_type != "":
                search_types.append(search_type)

    for ent in doc.ents:
        most_similar = get_similar(ent.text)
        definition = get_definition(ent.text)
        info = get_info(ent.text)

        if search_types:
            for search_type in search_types:
                print("XXX:",search_type)
                answer = get_answer(ent.text, search_type)
                if answer is not None:
                    data = json.dumps([r.data() for r in answer])
                    results_df = pd.read_json(data)

                    if not results_df.empty:
                        with col2:
                            st.markdown(''.join(['''<p style='color:#FDFD96;
                                        font-size:18px;
                                        text-align:left'>''',"",search_type.title(),"</style></p><"]),unsafe_allow_html=True)
                        for name, group in results_df.groupby('Source'):
                            with col2:
                                st.markdown(''.join(['''<i><p style='color:RoyalBlue;
                                            font-size:15px;
                                            text-align:left'>''',"Source: ",name,"</style></p></i>"]),unsafe_allow_html=True)

                            if 'Class' in group.columns:
                                if ent.text.title() in group['Class'].values:
                                    group = group.drop('Class', axis=1)
                                elif len(np.unique(group['Class'].values))==1:
                                    #for cases where class are all the same
                                    #eg query: "high blood pressure management"
                                    #further edit can be with reference to queries like "what cause diabetes"
                                    group = group.drop('Class', axis=1)
                                if group['Notes'].isna().sum()==group.shape[0]:
                                    #drop Notes column if all are NA
                                    #eg query: "high blood pressure management", "diabetes medication" 
                                    group = group.drop('Notes', axis=1)
                            
                            if not group.empty:
                                with col2:
                                    if 'Class' in group.columns:
                                        #for cases where class value and answer value is the same
                                        #eg query: "test for diabetes"
                                        #drops the class: test, test: test row
                                        group = group.loc[group.iloc[:,0]!=group.iloc[:,1],:]
                                    if 'Source' in group.columns:
                                        group.Source = group.Source.fillna("-")
                                    if 'Notes' in group.columns:
                                        group["Notes"] = group["Notes"].fillna("-")
                                    if 'Riskfactor' in group.columns:
                                        #changes from Riskfactor to Risk Factor
                                        group = group.rename({'Riskfactor':'Risk Factor'},axis=1)
                                    group = group.drop('Source', axis=1)
                                    #group = group.rename(columns=group.iloc[0]).drop(group.index[0])
                                    st.table(group)

        if most_similar is not None:
            data = json.dumps([r.data() for r in most_similar])
            results_df = pd.read_json(data)
            similar_lst = []
            similar_item = ""    
            with col1:
                for index, row in results_df.iterrows():
                    if 'Most_Similar' in results_df.columns:
                        item = row['Most_Similar']
                        similar_lst.append(item)
                similar_item = ', '.join([str(x) for x in similar_lst])

                if similar_item is not "":
                    st.info("Related To: " + similar_item) 

            with col1:
                for index, row in results_df.iterrows():
                        item = row['Most_Similar']
                        recommended_info = get_info(item)
                        if recommended_info is not None:
                            data = json.dumps([r.data() for r in recommended_info])
                            results_df = pd.read_json(data)
                            if 'Info' in results_df.columns:
                                st.markdown(''.join(['''<p style='color:#FDFD96;
                                           font-size:15px;
                                           text-align:left'>''',"&nbsp;&nbsp;&nbsp;Recommended Info: ",item,"</style></p>"]),unsafe_allow_html=True)

                                for name, group in results_df.groupby('Source'):
                                    with col1:
                                        st.markdown(''.join(['''<i><p style='color:RoyalBlue;
                                                    font-size:15px;
                                                    text-align:right'>''',"Source: ",name,"</style></p></i>"]),unsafe_allow_html=True)
                                        group = group.drop('Source', axis=1)
                                        st.table(group)

        if definition is not None:
            data = json.dumps([r.data() for r in definition])
            results_df = pd.read_json(data)
            if 'Definition' in results_df.columns:
                with col1:
                    with st.expander("See definition"):
                        st.warning(results_df['Definition'][0])
                        st.markdown(''.join(['''<i><p style='color:RoyalBlue;
                                           font-size:15px;
                                           text-align:right'>''',"Source: ",results_df['Source'][0],"</style></p></i>"]),unsafe_allow_html=True)

        if info is not None:
            data = json.dumps([r.data() for r in info])
            results_df = pd.read_json(data)
        
            with st.expander("See more info"):
                if 'Info' in results_df.columns:
                    for index, row in results_df.iterrows():
                        st.info(row['Info'])
                        st.markdown(''.join(['''<i><p style='color:RoyalBlue;
                                           font-size:15px;
                                           text-align:right'>''',"Source: ",results_df['Source'][index],"</style></p></i>"]),unsafe_allow_html=True)
