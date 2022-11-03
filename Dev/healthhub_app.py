import configparser
import json
import spacy
import spacy_dbpedia_spotlight
import spacy_streamlit
import streamlit as st
import pandas as pd
import numpy as np

from neo4j import GraphDatabase

config = configparser.ConfigParser()

config.read('../../healthhub.prop')

driver = GraphDatabase.driver("bolt://"+config['local-neo4j']['uri'], auth=(config['local-neo4j']['user'], config['local-neo4j']['password']))


st.set_page_config(
    page_title="Health Knowledge Hub",
    layout='wide'
)

@st.experimental_singleton
def load_models():
    model = spacy.load('en_core_web_lg')
    model.add_pipe('dbpedia_spotlight')
    return model

nlp = load_models()

def get_similar(entity):
    if entity != '':
        with driver.session() as session:
            query = """
                    match (n)-[:related_to]-(x)
                    where (n.type = 'Disease' or n.type = 'Condition') and n.name =~ '(?i)""" + entity + """' and n.text <> ""
                    return distinct x.name as Most_Similar, n.name as Name
                    """
        return session.run(query)

def get_definition(entity):
    if entity != '':
        with driver.session() as session:
            query = """
                    match (n)
                    where (n.type = 'Disease' or n.type = 'Condition' or n.type = 'Vaccination') and n.name =~ '(?i)""" + entity + """' and n.text <> ""
                    return distinct n.text as Definition, n.source as Source, n.name as Name
                    """
        return session.run(query)

def get_primary_answer(entity, type):
    type = type.title()
    if entity != '' and type != '' and type.lower() != entity.lower():
        with driver.session() as session:
            query = """
                    match (n)-[r]-(x)
                    where n.type =~ '(?i)"""+type+"""' and r.name =~ '(?i)""" + entity + """' and not x.name =~ '(?i)""" + entity + """'
                    return distinct x.name as """+type+""", r.source as Source, r.text as Notes, r.name as Name
                    """
            #print(query)
        return session.run(query)

def get_secondary_answer(entity, subject, object):
    subject = subject.title()
    object = object.title()
    with driver.session() as session:
        query = """
                match (x)-[r1]-(n)-[r2]-(y)
                where n.type =~ '(?i)"""+subject+"""' and n.name =~ '(?i)""" + entity + """' and x.type =~ '(?i)"""+object+"""' and not y.type =~ '(?i)"""+object+"""'
                return distinct x.name as Type, y.name as """+subject+"""
                """
    return session.run(query)


def get_info(entity):
    if entity != '':
        with driver.session() as session:
            query = """
                    match (n:Info)-[r]-(x)
                    where r.name =~ '(?i)""" + entity + """'
                    return distinct r.text as Info, r.source as Source, r.name as Name, r.type as Type
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

    subject, object = "", ""

    doc = nlp(query)
    
    for token in doc:
        #print(token.text, token.lemma_, token.pos_, token.tag_, token.dep_, token.shape_, token.is_alpha, token.is_stop)

        if token.dep_ in ['nsubj'] and token.pos_ == 'NOUN':
            if token.lemma_ in ['effect']:
                subject = 'effect'
        
        elif token.dep_ in ['dobj', 'pobj'] and token.pos_ == 'NOUN':
            if token.lemma_ in ['vaccine']:
                object = 'vaccination'

        elif token.dep_ in ['nsubj', 'conj', 'ROOT', 'dobj', 'pobj'] and token.pos_ == 'NOUN':
            if token.lemma_ in ['effect']:
                search_type = 'effect'
            elif token.lemma_ in ['medication', 'medicine', 'treatment']:
                search_type = 'prescription'
            elif token.lemma_ == 'management':
                search_type = 'management'
            elif token.lemma_ == 'screening':
                search_type = 'checkup'
            elif token.lemma_ in ['risk']:
                search_type = 'riskfactor'
            elif token.lemma_ in ['bill', 'payment', 'subsidy']:
                search_type = 'expenses'
            elif token.lemma_ in ['vaccine']:
                search_type = 'vaccination'
            else:
                search_type=token.lemma_
            if search_type != "":
                search_types.append(search_type)
        elif (token.dep_ in ['ROOT', 'conj'] or token.dep_ == 'relcl' or token.dep_ in ['ccomp', 'xcomp'])  and token.pos_ == 'VERB':
            if token.lemma_ in ['avoid', 'manage', 'prevent']:
                search_type='management'
            elif token.lemma_ in ['cure', 'medicate', 'treat']:
                search_type = 'prescription'
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
        if ent.text[0].isupper():
            most_similar = get_similar(ent.text)
            definition = get_definition(ent.text)
            info = get_info(ent.text)

            secondary_answer = get_secondary_answer(ent.text, subject, object)

            if secondary_answer is not None:
                data = json.dumps([r.data() for r in secondary_answer])
                results_df = pd.read_json(data)

                for name, group in results_df.groupby('Type'):
                    with col2:
                        st.markdown(''.join(['''<i><p style='color:RoyalBlue;
                                    font-size:15px;
                                    text-align:left'>''',"Type: ",name,"</style></p></i>"]),unsafe_allow_html=True)
                        group = group.drop('Type', axis=1)
                        st.table(group)

            if search_types:
                for search_type in search_types:
                    #print("Search Type:",search_type)
                    primary_answer = get_primary_answer(ent.text, search_type)

                    if primary_answer is not None:
                        data = json.dumps([r.data() for r in primary_answer])
                        results_df = pd.read_json(data)

                        if not results_df.empty:
                            name_label = results_df['Name'][0]

                            if 'Riskfactor' in results_df.columns:
                                results_df = results_df.rename({'Riskfactor':'Risk Factor'},axis=1)
                            elif 'Effect' in results_df.columns:
                                results_df = results_df.rename({'Effect':'Side Effect'},axis=1)
                                results_df = results_df[~results_df['Side Effect'].str.contains("COVID-19")]

                            answer_header = str(results_df.columns[1]).title()

                            with col2:
                                if answer_header=="Risk Factor":
                                    st.markdown(''.join(['''<p style='color:#daa520;
                                            font-size:18px;
                                            text-align:left'>''',"",""+answer_header+"(s)"+" for "+name_label,"</style></p><"]),unsafe_allow_html=True)
                                else:
                                    st.markdown(''.join(['''<p style='color:#daa520;
                                            font-size:18px;
                                            text-align:left'>''',"",answer_header+" for "+name_label,"</style></p><"]),unsafe_allow_html=True)

                            for name, group in results_df.groupby('Source'):
                                with col2:
                                    st.markdown(''.join(['''<i><p style='color:RoyalBlue;
                                                font-size:15px;
                                                text-align:left'>''',"Source: ",name,"</style></p></i>"]),unsafe_allow_html=True)

                                if group['Notes'].isna().sum()==group.shape[0]:
                                        group = group.drop('Notes', axis=1)
                                
                                if not group.empty:
                                    with col2:
                                        if 'Source' in group.columns:
                                            group.Source = group.Source.fillna("-")
                                        if 'Notes' in group.columns:
                                            group["Notes"] = group["Notes"].fillna("-")
                                        if 'Risk Factor' in group.columns:
                                            header = "Risk Factor(s) for " + name_label
                                        else:
                                            group = group.rename({search_type.title():search_type.title()+" for " + name_label}, axis=1)
                                        group = group.drop(['Name', 'Source'], axis=1)
                                        #group = group.rename(columns=group.iloc[0]).drop(group.index[0])
                                        st.table(group)


            if definition is not None:
                data = json.dumps([r.data() for r in definition])
                results_df = pd.read_json(data)
                if 'Definition' in results_df.columns:
                    definition_header = "See definition for " + results_df['Name'][0]
                    with col1:
                        with st.expander(definition_header):
                            st.warning(results_df['Definition'][0])
                            st.markdown(''.join(['''<i><p style='color:RoyalBlue;
                                            font-size:15px;
                                            text-align:right'>''',"Source: ", results_df['Source'][0],"</style></p></i>"]),unsafe_allow_html=True)

            
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
                        similar_item_header = "Related to " + results_df['Name'][0] + ": "
                        st.info(similar_item_header + similar_item)

                with col1:
                    related_lst=[]
                    related_info_lst=[]
                    for index, row in results_df.iterrows():
                            item = row['Most_Similar']
                            recommended_info = get_info(item)
                            if recommended_info is not None:
                                data = json.dumps([r.data() for r in recommended_info])
                                results_df = pd.read_json(data)
                                if 'Info' in results_df.columns:
                                    related_info_header = "Info for " + item
                                    results_df = results_df.rename({'Info':related_info_header}, axis=1)
                                    related_lst.append(item)

                                    for name, group in results_df.groupby('Source'):
                                        group = group.drop(['Name', 'Source', 'Type'], axis=1)
                                        related_info_lst.append([name, group])
                                    
                    if related_lst!=[]:
                        st.markdown(''.join(['''<p style='color:#daa520;
                                            font-size:18px;
                                            text-align:left'> Recommended Info </style></p>''']), unsafe_allow_html=True)

                        selection=st.radio("Select disease/condition to see more info",related_lst)
                        st.markdown(''.join(['''<i><p style='color:RoyalBlue;
                                                    font-size:15px;
                                                    text-align:right'>''',"Source: ", related_info_lst[related_lst.index(selection)][0],"</style></p></i>"]), unsafe_allow_html=True)
                        st.table(related_info_lst[related_lst.index(selection)][1])

            if info is not None:
                data = json.dumps([r.data() for r in info])
                results_df = pd.read_json(data)
                
                if 'Info' in results_df.columns:
                    info_header = "See more info for " + results_df['Name'][0]
                    info_types = list(set(list(results_df['Type'])))
                    with st.expander(info_header):
                        if not pd.isnull(np.array(info_types)).any():
                            info_selection = st.radio("Select type of info to view more",info_types)
                            info_df= results_df.loc[results_df['Type']==info_selection].reset_index(drop=True)
                            for index, row in info_df.iterrows():
                                st.info(row['Info'])
                                st.markdown(''.join(['''<i><p style='color:RoyalBlue;
                                                font-size:15px;
                                                text-align:right'>''',"Source: ",info_df['Source'][index],"</style></p></i>"]), unsafe_allow_html=True)
                        else:
                            for index, row in results_df.iterrows():
                                st.info(row['Info'])
                                st.markdown(''.join(['''<i><p style='color:RoyalBlue;
                                                font-size:15px;
                                                text-align:right'>''',"Source: ",results_df['Source'][index],"</style></p></i>"]), unsafe_allow_html=True)
            
