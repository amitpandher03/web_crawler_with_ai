import json
import chainlit as cl
from openai import OpenAI
from config import Config
from tavily import TavilyClient
from prompts import query_writer_instructions, summarizer_instructions, reflection_instructions

# Inizializzazione del client OpenAI con le configurazioni
client = OpenAI(base_url = Config.AI_API_URL, api_key = Config.AI_API_KEY)

# Funzione per interagire con l'AI 
def llm(developer_prompt, user_prompt, temperature = 0, response_format = {"type": "json_object"}):
    
    response = client.chat.completions.create(
        model = Config.LLM_MODEL,
        messages=[
            {"role": "developer", "content": developer_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=temperature,
        response_format=response_format
    )
    return response.choices[0].message.content

# Genera una query ottimizzata per la ricerca web
def optimize_search_query(research_topic):
    formatted_instructions = query_writer_instructions.format(research_topic = research_topic)
    result = llm(formatted_instructions, "Genera una query per la ricerca web:")
    obj = json.loads(result)
    return obj

def _format_content(result):
    return f"""
Fonte {result['title']}:\n===\n
URL: {result['url']}\n===\n
Contenuto più rilevante: {result['content']}\n===\n
"""

def web_research(search_query):
    tavily_api_key = Config.TAVILY_API_KEY
    max_results = 3
    include_raw = False

    client = TavilyClient(api_key = tavily_api_key)
    response = client.search(
                query=search_query,
                max_results=max_results,
                include_raw_content=include_raw
            )
    results = response.get('results', [])
    titles = [result['title'] for result in results ]
    contents = [_format_content(result) for result in results ]
    
    return {
        "sources_gathered": titles,
        "web_research_results": contents
    }

# Sintetizza i risultati della ricerca in un riassunto coerente
def summarize_sources(web_research_results, research_topic, running_summary=None):
    
    # current_results = web_research_results[-1] # Prende l'ultimo risultato
    current_results = "\n".join(web_research_results)
    
    if running_summary:
        message = (
            f"Estendi questo riassunto: {running_summary}\n\n"
            f"Con questi nuovi risultati: {current_results} "
            f"Sul tema: {research_topic}"
        )
    else:
        message = (
            f"Genera un riassunto di questi risultati: {current_results} "
            f"Sul tema: {research_topic}"
        )
    
    output_formatter = None # Vogliamo del testo semplice
    return llm(summarizer_instructions, message, 0.2, output_formatter)

# Analizza il riassunto corrente e genera una domanda di approfondimento
def reflect_on_summary(research_topic, running_summary):
    result = llm(
        reflection_instructions.format(research_topic=research_topic),
        f"Identifica una lacuna e genera una domanda per la prossima ricerca basandoti su: {running_summary}"
    )
    return json.loads(result)

@cl.on_message
async def main(message: cl.Message):
    # Add initial message elements
    msg = cl.Message(content="Iniziando la ricerca...", author="system_assistant")
    await msg.send()
    
    # Fase 1: Generazione della query iniziale
    user_message = message.content
    
    try:
        await cl.Message(content="Ottimizzando la query di ricerca...", author="system_assistant").send()
        osq = optimize_search_query(user_message)

        # feedback per l'utente
        query, aspect, reason = osq['query'], osq['aspect'], osq['reason']
        await cl.Message(
            author="system_assistant", 
            content=f"Query di ricerca ottimizzata:\n {query}.\n Mi sono soffermato su questo aspetto:\n {aspect}.\n Per questo motivo:\n {reason}.\n"
        ).send()

        # Fase 2: Ciclo di ricerca e approfondimento
        running_summary = None
        max_cycles = 3

        while max_cycles > 0:
            # Esegui la ricerca web
            await cl.Message(content="Cercando informazioni sul web...", author="system_assistant").send()
            results = web_research(query)

            # Add sources feedback
            titles = "\n".join(results['sources_gathered'])
            await cl.Message(
                author="system_assistant", 
                content=f"Fonti trovate:\n{titles}"
            ).send()
            
            # Genera o aggiorna il riassunto
            summary = summarize_sources(results['web_research_results'], query, running_summary)
            running_summary = summary

            # feedback per l'utente
            await cl.Message(author="system_assistant", content=f"Riassunto attuale:\n{summary}").send()

            max_cycles -= 1
            if max_cycles <= 0:
                break

            # Genera la prossima query di approfondimento
            ros = reflect_on_summary(query, summary)
            query = ros.get('domanda_approfondimento', f"Dimmi di più su {query}")
            lacuna_conoscenza = ros.get('lacuna_conoscenza', "")

            await cl.Message(
                author="system_assistant", 
                content=f"Prossima ricerca:\n{query}\nMotivazione:\n{lacuna_conoscenza}"
            ).send()
        
    except Exception as e:
        await cl.Message(
            author="system_assistant",
            content=f"Si è verificato un errore durante la ricerca: {str(e)}"
        ).send()
        return

    # Risultato finale
    await cl.Message(
        author="segugio_assistant",
        content=f"Risposta alla tua domanda:\n\n{message.content}\n\nRisposta finale:\n\n{running_summary}"
    ).send()