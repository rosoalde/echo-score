# /home/romina/RRSS_FORTMAT/web_FORMAT/Web_Proyecto/clean_project/scrapers/telegram_API.py
from search_to_telegram import search_messages #type: ignore


def prueba():
    todo = search_messages("fútbol", "2026-07-01", "2026-07-31")
    print("########################################################################")
    print("########################################################################")
    print("########################################################################")

    print("                                TELEGRAM                                ")
    print("\n\n")

    print(todo[2])
    print(f"\ntamaño: {len(todo)}")
    print("\n\n")
    print("########################################################################")
    print("########################################################################")
    print("########################################################################")
