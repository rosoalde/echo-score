from clean_project.prompts.topics import get_prompt as get_prompt_topics
from clean_project.prompts.pilares import get_prompt as get_prompt_pilares

def build_sentiment_prompt(keywords):
    return get_prompt_topics(keywords)

def build_acceptance_prompt(keywords):
    return get_prompt_pilares(keywords)
