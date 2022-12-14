import configparser
import json
import spacy
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
    model = spacy.load("en_core_sci_lg")
    return model

nlp = load_models()

def get_similar(entity):
    if entity != '':
        with driver.session() as session:
            query = """
                    match (n)-[:related_to]-(x)
                    where (n.type = 'Disease' or n.type = 'Condition' or n.type = 'Medication') and n.name =~ '(?i)""" + entity + """' and n.text <> ""
                    return distinct x.name as Most_Similar, n.name as Name
                    """
        return session.run(query)

def get_definition(entity):
    if entity != '':
        with driver.session() as session:
            query = """
                    match (n)
                    where (n.type = 'Disease' or n.type = 'Condition' or n.type = 'Vaccination' or n.type = 'Medication') and n.name =~ '(?i)""" + entity + """' and n.text <> ""
                    return distinct n.text as Definition, n.source as Source, n.name as Name
                    """
        return session.run(query)


def get_primary_answer(entity, type):
    type = type.title()
    if '-' in type:
        type = type.replace("-","")
    if entity != '' and type != '' and type.lower() != entity.lower():
        with driver.session() as session:
            query = """
                    match (n)-[r]-(x)
                    where n.type =~ '(?i)"""+type+"""' and r.name =~ '(?i)""" + entity + """' and not x.name =~ '(?i)""" + entity + """'
                    return distinct x.name as """+type+""", r.source as Source, r.text as Notes, r.name as Name
                    """
        return session.run(query)

def get_secondary_answer(entity, subject, object):
    subject = subject.title()
    object = object.title()
    with driver.session() as session:
        query = """
                match (x)-[r1]-(n)-[r2]-(y)
                where n.type =~ '(?i)"""+subject+"""' and n.name =~ '(?i)""" + entity + """' and x.type =~ '(?i)"""+object+"""' and not y.type =~ '(?i)"""+object+"""'
                return distinct r2.name as Type, y.name as """+subject+""",r2.source as Source,r2.text as Notes
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

    subject, object, compound = "", "", ""
    compound_dict = {}

    doc = nlp(query)
    
    for token in doc:
        #print(token.text, token.lemma_, token.pos_, token.tag_, token.dep_, token.shape_, token.is_alpha, token.is_stop)
        if token.dep_ in ['compound'] and token.pos_ == 'NOUN':
            compound_dict['compound'] = token.lemma_
            compound_dict['compound_idx'] = token.i
            compound = token.lemma_
        if token.dep_ in ['amod'] and token.pos_ == 'ADJ':
            compound_dict['modifier'] = token.lemma_
            compound_dict['modifier_idx'] = token.i
        if token.dep_ in ['nsubj'] and token.pos_ == 'NOUN':
            if token.lemma_ in ['effect']:
                subject = 'effect'
            elif token.lemma_ in ['instruction']:
                subject='instruction'
            elif token.lemma_ in ['precaution']:
                subject='precaution'
        elif token.dep_ in ['dobj', 'pobj', 'nmod'] and token.pos_ == 'NOUN':
            if token.lemma_ in ['vaccine']:
                object = 'vaccination'
            elif token.lemma_ in ['medicine', 'medication']:
                object = 'medication'

        if token.dep_ in ['nsubj', 'nmod', 'conj', 'ROOT', 'dobj', 'pobj'] and token.pos_ == 'NOUN':
            if token.lemma_ in ['effect']:
                search_type = 'effect'
            elif token.lemma_ in ['cure', 'medication', 'medicine', 'treatment']:
                search_type = 'prescription'
            elif token.lemma_ == 'management':
                search_type = 'management'
            elif token.lemma_ == 'screening':
                search_type = 'checkup'
            elif token.lemma_ in ['risk']:
                search_type = 'riskfactor'
            elif token.lemma_ in ['bill', 'expense', 'payment', 'subsidy']:
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
                
    prev_compound=""
    for ent in doc.ents:
        words = str(ent.text).split()
        if 'modifier_idx' in compound_dict.keys() and 'compound_idx' in compound_dict.keys():
            diff_idx = compound_dict['compound_idx'] - compound_dict['modifier_idx']
            if diff_idx == 1:
                compound = compound_dict['modifier'] + " " + compound_dict['compound']
        while prev_compound!=compound:
            if len(words) > 1:
                most_similar = get_similar(compound)
                definition = get_definition(compound)
                info = get_info(compound)
            else:
                most_similar = get_similar(ent.text)
                definition = get_definition(ent.text)
                info = get_info(ent.text)
            if subject != "" and object != "":
                if len(words) > 1:
                    secondary_answer = get_secondary_answer(compound, subject, object)
                else:
                    secondary_answer = get_secondary_answer(ent.text, subject, object)
                ans_dict={}
                if secondary_answer is not None:
                    
                    data = json.dumps([r.data() for r in secondary_answer])
                    results_df = pd.read_json(data)
                        
                    if 'Type' in results_df.columns:
                        
                        for name, group in results_df.groupby('Type'):
                            if get_similar(name) is not None:
                                med_class_data = json.dumps([r.data() for r in get_similar(name)])
                                med_class_df = pd.read_json(med_class_data)
                                if 'Most_Similar' in med_class_df.columns:
                                    for index,row in med_class_df.iterrows():
                                        grp_item = row['Most_Similar']
                                        if grp_item not in ans_dict:
                                            ans_dict[grp_item]=[[name,group]]
                                        else:
                                            ans_dict[grp_item].append([name,group])
                                else:
                                    if name not in ans_dict:
                                        ans_dict[name]=[[name,group]]
                                    else:
                                        ans_dict[name].append([name,group])
                    with col2:
                        if ans_dict!={}:
                            answer_selection=st.radio("Select an option/group to view its corresponding answers", ans_dict.keys())
                            if len(ans_dict[answer_selection])==1:
                                for i in ans_dict[answer_selection]:
                                    if 'Type' in i[1].columns:
                                        i[1]=i[1].drop('Type',axis=1)
                                    if 'Source' in i[1].columns:
                                        for source_name,med_ans in i[1].groupby('Source'):
                                            st.markdown(''.join(['''<p style='color:#daa520;
                                                                    font-size:18px;
                                                                    text-align:left'>''',"",""+i[0],"</style></p>",
                                                                 '''<i><p style='color:RoyalBlue;font-size:15px;text-align:right'>''',"Source: ",""+source_name,"</style></p></i>"]),unsafe_allow_html=True)
                                    
                                            if not med_ans.empty:
                                                med_ans=med_ans.drop('Source',axis=1)
                                                if 'Effect' in med_ans.columns:
                                                    med_ans = med_ans.rename({'Effect':'Side Effect'},axis=1)
                                                    med_ans = med_ans[~med_ans['Side Effect'].str.contains("COVID-19|Diabetes|High Blood Pressure|High Cholesterol|Stroke|Colorectal Cancer")]
                                                elif 'Instruction' in med_ans.columns:
                                                    med_ans = med_ans[~med_ans['Instruction'].str.contains("COVID-19|Diabetes|High Blood Pressure|High Cholesterol|Stroke|Colorectal Cancer")]
                                                elif 'Precaution' in med_ans.columns:
                                                    med_ans = med_ans[~med_ans['Precaution'].str.contains("COVID-19|Diabetes|High Blood Pressure|High Cholesterol|Stroke|Colorectal Cancer")]                                            
                                                if med_ans['Notes'].isna().sum()==med_ans.shape[0]:
                                                    med_ans = med_ans.drop('Notes', axis=1)
                                                if 'Notes' in med_ans.columns:
                                                    med_ans['Notes'] = med_ans['Notes'].fillna("-")
                                                st.table(med_ans)
                            else:
                                list_of_options=[]
                                specific_options=[]
                                col2.caption("Select an option belonging to this group to view its corresponding answers. You may select more than one to compare.")
                                for i in ans_dict[answer_selection]:
                                    list_of_options.append(i[0])
                                    specific_med_selection = col2.checkbox(i[0])
                                    if specific_med_selection:
                                        specific_options.append(i[0])
                                for i in specific_options:
                                    ans=ans_dict[answer_selection][list_of_options.index(i)][1]
                                    if 'Type' in ans.columns:
                                        ans=ans.drop('Type',axis=1)
                                    if 'Source' in ans.columns:
                                        for source_name,med_ans in ans.groupby('Source'):
                                            st.markdown(''.join(['''<p style='color:#daa520;
                                                                font-size:18px;
                                                                text-align:left'>''',"",""+i,"</style></p>",
                                                                '''<i><p style='color:RoyalBlue;
                                                                font-size:15px;
                                                                text-align:right'>''',"Source: ",source_name,"</style></p></i>"]),unsafe_allow_html=True)

                                            if not med_ans.empty:
                                                med_ans=med_ans.drop('Source',axis=1)
                                                if 'Effect' in med_ans.columns:
                                                    med_ans = med_ans.rename({'Effect':'Side Effect'},axis=1)
                                                    med_ans = med_ans[~med_ans['Side Effect'].str.contains("COVID-19|Diabetes|High Blood Pressure|High Cholesterol|Stroke|Colorectal Cancer")]
                                                elif 'Instruction' in med_ans.columns:
                                                    med_ans = med_ans[~med_ans['Instruction'].str.contains("COVID-19|Diabetes|High Blood Pressure|High Cholesterol|Stroke|Colorectal Cancer")]
                                                elif 'Precaution' in med_ans.columns:
                                                    med_ans = med_ans[~med_ans['Precaution'].str.contains("COVID-19|Diabetes|High Blood Pressure|High Cholesterol|Stroke|Colorectal Cancer")]
                                                if med_ans['Notes'].isna().sum()==med_ans.shape[0]:
                                                    med_ans = med_ans.drop('Notes', axis=1)
                                                if 'Notes' in med_ans.columns:
                                                    med_ans['Notes'] = med_ans['Notes'].fillna("-")
                                                st.table(med_ans)
                            st.markdown("""---""")
                                            
            
            if search_types:
                for search_type in search_types:
                    #print("Search Type:",search_type)
                    words = str(ent.text).split()
                    if len(words) > 1 and compound != '':
                        primary_answer = get_primary_answer(compound, search_type)
                    else:
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
                                results_df = results_df[~results_df['Side Effect'].str.contains("COVID-19|Diabetes|High Blood Pressure|High Cholesterol|Stroke|Colorectal Cancer")]
                            elif 'Instruction' in results_df.columns:
                                results_df = results_df[~results_df['Instruction'].str.contains("COVID-19|Diabetes|High Blood Pressure|High Cholesterol|Stroke|Colorectal Cancer")]
                            elif 'Precaution' in results_df.columns:
                                results_df = results_df[~results_df['Precaution'].str.contains("COVID-19|Diabetes|High Blood Pressure|High Cholesterol|Stroke|Colorectal Cancer")]
                            answer_header = str(results_df.columns[0]).title()

                            with col2:
                                for name, group in results_df.groupby('Source'):
                                    if answer_header=="Risk Factor":
                                        st.markdown(''.join(['''<p style='color:#daa520;
                                                font-size:18px;
                                                text-align:left'>''',"",""+answer_header+"(s)"+" for "+name_label,"</style></p>",
                                                '''<i><p style='color:RoyalBlue;
                                                font-size:15px;
                                                text-align:right'>''',"Source: ",name,"</style></p></i>"]),unsafe_allow_html=True)
                                    else:
                                        st.markdown(''.join(['''<p style='color:#daa520;
                                                font-size:18px;
                                                text-align:left'>''',"",answer_header+" for "+name_label,"</style></p>",
                                                '''<i><p style='color:RoyalBlue;
                                                font-size:15px;
                                                text-align:right'>''',"Source: ",name,"</style></p></i>"]),unsafe_allow_html=True)

                                    if group['Notes'].isna().sum()==group.shape[0]:
                                            group = group.drop('Notes', axis=1)
                                    
                                    if not group.empty:
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
            prev_compound=compound

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
                related_lst1=[] 
                related_info_lst=[]
                related_lst2=[] 
                related_def_lst=[]
                for index, row in results_df.iterrows():
                    item = row['Most_Similar']
                    recommended_info = get_info(item)
                    results_df = pd.read_json(data)
                    recommended_def = get_definition(item)
                    if recommended_info is not None:
                        data = json.dumps([r.data() for r in recommended_info])
                        results_df = pd.read_json(data)
                        if 'Info' in results_df.columns:
                            related_info_header = "Info for " + item
                            results_df = results_df.rename({'Info':related_info_header}, axis=1)
                            related_lst1.append(item)

                            for name, group in results_df.groupby('Source'):
                                group = group.drop(['Name', 'Source', 'Type'], axis=1)
                                related_info_lst.append([name, group])
                                
                    if recommended_def is not None:
                        data = json.dumps([r.data() for r in recommended_def])
                        results_df = pd.read_json(data)
                        if 'Definition' in results_df.columns:
                            related_def_header = "Definition for " + item
                            results_df = results_df.rename({'Definition':related_def_header}, axis=1)
                            related_lst2.append(item)
                            for name, group in results_df.groupby('Source'):
                                group = group.drop(['Name', 'Source'], axis=1)
                                related_def_lst.append([name, group])
                if related_lst2!=[]:
                    st.markdown("""---""")
                    st.markdown(''.join(['''<p style='color:#daa520;
                                        font-size:18px;
                                        text-align:left'>Definition </style></p>''']), unsafe_allow_html=True)
                    def_selection=st.radio("Select disease/condition to see more definitions",related_lst2)
                    st.markdown(''.join(['''<i><p style='color:RoyalBlue;
                                                font-size:15px;
                                                text-align:right'>''',"Source: ", related_def_lst[related_lst2.index(def_selection)][0],"</style></p></i>"]), unsafe_allow_html=True)
                    st.table(related_def_lst[related_lst2.index(def_selection)][1])
                    
                    
                if related_lst1!=[]:
                    st.markdown("""---""")
                    st.markdown(''.join(['''<p style='color:#daa520;
                                        font-size:18px;
                                        text-align:left'> Recommended Info </style></p>''']), unsafe_allow_html=True)

                    info_selection=st.radio("Select disease/condition to see more info",related_lst1)
                    st.markdown(''.join(['''<i><p style='color:RoyalBlue;
                                                font-size:15px;
                                                text-align:right'>''',"Source: ", related_info_lst[related_lst1.index(info_selection)][0],"</style></p></i>"]), unsafe_allow_html=True)
                    st.table(related_info_lst[related_lst1.index(info_selection)][1])


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
        
