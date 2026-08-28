import bs4


class Scraper:
    soup: bs4.BeautifulSoup

    def __init__(self, html: str):
        self.soup = bs4.BeautifulSoup(html, "html.parser")

    def get_title_page(self) -> str:
        return self.soup.title.string if self.soup.title else ""
