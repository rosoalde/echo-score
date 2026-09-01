
import asyncio
import clean_project.config.settings as config

from clean_project.scrapers.bluesky_scraper import run_bluesky
from clean_project.scrapers.reddit_scraper import run_reddit
from clean_project.scrapers.linkedin_scraper import run_linkedin
from clean_project.scrapers.youtube_scraper import run_youtube
from clean_project.scrapers.twitter_scraper import run_twitter
from clean_project.scrapers.tiktok_scraper import run_tiktok
from clean_project.analysis.llm_analysis import llm_analysis
from clean_project.analysis.metrics import metrics



def run_pipeline():
    print("#########################################")
    print("prueba")
    print("#########################################")
    
    # try:
    #     print("▶ Ejecutando scraper LinkedIn...")
    #     run_linkedin(config)
    # except:
    #     print("No se pudo ejecutar el scraper de LinkedIn. Continuando con los demás scrapers...")

    try:    
        print("▶ Ejecutando scraper Bluesky...")
        run_bluesky(config)  
    except:
        print("No se pudo ejecutar el scraper de Bluesky. Continuando con los demás scrapers...")    

    # try:
    #     print("▶ Ejecutando scraper Reddit...")
        
    #     asyncio.run(run_reddit(config))
    # except:
    #     print("No se pudo ejecutar el scraper de Reddit. Continuando con los demás scrapers...")

    # try:    
    #     print("▶ Ejecutando scraper YouTube...")
    #     run_youtube(config)   
    # except:
    #     print("No se pudo ejecutar el scraper de YouTube. Continuando con los demás scrapers...")    

    # try:
    #     print("▶ Ejecutando scraper Twitter...")
    #     run_twitter(config)
    # except:
    #     print("No se pudo ejecutar el scraper de Twitter. Continuando con los demás scrapers...")

    # try:
    #     print("▶ Ejecutando scraper TikTok...")
    #     run_tiktok(config)
    # except:
    #     print("No se pudo ejecutar el scraper de TikTok. Continuando con los demás scrapers...")   

    # try:
    #     print("▶ Analizar sentimiento con nuevo LLM:")
    #     sentiment_result = llm_analysis()
    #     print(sentiment_result)
    # except:
    #     print("No se pudo ejecutar el análisis de sentimiento con LLM. Continuando con el cálculo de métricas...")  
    # try:    
    #     print("▶ Calcular métricas:")
    #     metrics_result = metrics()
    #     print(metrics_result)
    # except:
    #     print("No se pudo ejecutar el cálculo de métricas.")    
# para correr el pipeline desde pipeline.py
# if __name__ == "__main__":
#     run_pipeline()