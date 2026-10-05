from clinic.rag import Retriever, load_articles
from data.seed import SERVICES


def test_every_article_has_both_languages():
    for article in load_articles():
        assert article.ar and article.en, article.slug


def test_each_article_is_found_by_its_own_title():
    retriever = Retriever()
    for article in retriever.articles:
        assert retriever.search(article.title, k=1)[0][0].slug == article.slug


def test_unrelated_question_scores_low():
    retriever = Retriever()
    assert retriever.search("do you sell perfume?", k=1)[0][1] < 0.06


def test_every_bookable_service_has_a_price_in_the_knowledge_base():
    prices = {a.slug: a.ar for a in load_articles()}
    all_prices = prices["prices-dental"] + prices["prices-skin"]
    for _, _, name_ar, *_ in SERVICES:
        assert name_ar.split()[0] in all_prices, name_ar
