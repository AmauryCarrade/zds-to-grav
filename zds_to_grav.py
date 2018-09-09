"""
Utility to convert a Zeste de Savoir article or opinion to the Grav format.
"""

import io
import json
import re
import shutil
import sys
import os

from datetime import time, datetime
from hashlib import sha256
from zipfile import ZipFile

import click
import requests
import yaml

from bs4 import BeautifulSoup
from path import Path
from slugify import UniqueSlugify


__version__ = "1.0.0"


@click.command()
@click.option(
    "--template-name",
    default="item",
    help="The template name to use (default item for blog entries)",
)
@click.option("--lang", default=None, help="The lang to use (default to none)")
@click.option(
    "--slug",
    default=None,
    help="The default page slug to use. If not provided, fallbacks to a slugified version of the title. The folder will never be numbered.",
)
@click.option(
    "--to",
    default=None,
    help="Where to store the Grav article directory (default to the archive directory, or the current directory if input by URL).",
)
@click.argument("zds-archive")
def zds_to_grav(zds_archive, template_name, lang, slug, to):
    """
    Converts a Zeste de Savoir article or opinion for Grav.

    The archive argument can either be a path to a downloaded archive or the URL
    to an article or an opinion on Zeste de Savoir. URL are preferred as it allows
    to fetch metadata not contained in the archive (tags, categories, authors).
    """
    try:
        tags = []
        categories = []
        authors = []
        date = None
        link = None

        if zds_archive.startswith("http://") or zds_archive.startswith("https://"):
            if not zds_archive.startswith(
                "http://zestedesavoir.com/"
            ) and not zds_archive.startswith("https://zestedesavoir.com/"):
                click.secho(
                    "Invalid URL, only Zeste de Savoir URLs are accepted. Aborting.",
                    fg="red",
                    bold=True,
                )
                return

            click.echo("Downloading archive and metadata from Zeste de Savoir…")

            link = zds_archive

            r = requests.get(zds_archive)
            if not r.ok:
                click.secho(
                    f"Cannot download Zeste de Savoir webpage: {r.status_code} {r.reason}",
                    fg="red",
                    bold=True,
                )
                return

            zds_page = r.text
            zds_soup = BeautifulSoup(zds_page, "html.parser")

            click.echo("Retrieving metadata…")

            download_link = zds_soup.find("aside", class_="sidebar")
            if download_link:
                download_link = download_link.find("a", class_="download")
            if download_link:
                download_link = download_link.get("href")

            if not download_link:
                click.secho(
                    "Cannot find the download link on the page. Maybe it was not generated by Zeste de Savoir? Aborting.",
                    fg="red",
                    bold=True,
                )
                return

            if download_link.startswith("/"):
                download_link = f"https://zestedesavoir.com{download_link}"

            tags_list = zds_soup.find("ul", class_="taglist")
            if tags_list:
                for tag in tags_list.find_all("li"):
                    tags.append(tag.string.strip())

            authors_block = (
                zds_soup.find("article", class_="content-wrapper")
                .find("header")
                .find("div", class_="authors")
            )
            if authors_block:
                meta_lists = authors_block.find_all("ul")

                authors_list = meta_lists[0] if len(meta_lists) > 0 else None
                categories_list = meta_lists[1] if len(meta_lists) > 1 else None

                if authors_list:
                    for author in authors_list.find_all("li"):
                        authors.append(author.a.span.string.strip())

                if categories_list:
                    for category in categories_list.find_all("a"):
                        categories.append(category.string.strip())

            date_elem = (
                zds_soup.find("article", class_="content-wrapper")
                .find("header")
                .find("span", class_="pubdate")
            )
            if date_elem:
                date_elem = date_elem.find("time")
                if date_elem:
                    date = datetime.fromisoformat(date_elem["datetime"])

            click.echo(f"Downloading content archive from {download_link}…")

            r = requests.get(download_link, stream=True)

            if not r.ok:
                click.secho(
                    f"Cannot download Zeste de Savoir webpage: {r.status_code} {r.reason}",
                    fg="red",
                    bold=True,
                )
                return

            zds_archive = io.BytesIO(r.content)

            if not to:
                to = os.getcwd()

        elif not to:
            to = Path(zds_archive).parent

        to = to.rstrip("/") + "/"

        with ZipFile(zds_archive) as archive:
            manifest = {}

            with archive.open("manifest.json", "r") as manifest:
                manifest = json.loads(manifest.read())

            if manifest["version"] < 2:
                click.secho(
                    f"Unsupported manifest version {manifest['version']} (only version 2 is supported)",
                    err=True,
                    fg="red",
                    bold=True,
                )
                return

            if manifest["type"] not in ["ARTICLE", "OPINION"]:
                click.secho(
                    f"Unsupported content type {manifest['type']} (only articles and opinions are supported at the moment); aborting.",
                    err=True,
                    fg="red",
                    bold=True,
                )
                return

            if not slug:
                slug = (
                    manifest["slug"]
                    if "slug" in manifest
                    else "unnamed-content-" + str(int(time.time()))
                )

            to += slug + "/"
            to = Path(to)
            to.mkdir_p()

            markdown_content = ""

            if "introduction" in manifest:
                with archive.open(manifest["introduction"]) as introduction:
                    markdown_content = download_and_replace_markdown_images(
                        get_content(introduction), to
                    )

            if "children" in manifest:
                for child in manifest["children"]:
                    if not child["object"] == "extract":
                        continue
                    with archive.open(child["text"]) as extract:
                        markdown_content += "\n\n\n"
                        markdown_content += f"# {child['title']}\n\n"
                        markdown_content += download_and_replace_markdown_images(
                            shift_markdown_headers(get_content(extract)), to
                        )

            if "conclusion" in manifest:
                with archive.open(manifest["conclusion"]) as conclusion:
                    markdown_content += "\n\n\n------\n\n\n"
                    markdown_content += download_and_replace_markdown_images(
                        get_content(conclusion), to
                    )

            # fmt: off
            markdown_frontmatter = {
                "title": manifest["title"] if "title" in manifest else f"Unnamed {manifest['type'].lower()}",
                "abstract": manifest["description"] if "description" in manifest else "",
                "taxonomy": {
                    "author": authors, 
                    "category": categories,
                    "tag": tags
                },
            }
            # fmt: on

            if date:
                markdown_frontmatter["date"] = date.strftime("%H:%M %d-%m-%Y")

            if "licence" in manifest:
                if manifest["licence"].startswith("CC"):
                    markdown_frontmatter["license"] = (
                        manifest["licence"].lower().replace("cc ", "")
                    )

            if link:
                markdown_frontmatter["canonical"] = link

            markdown_frontmatter_raw = "---\n"
            markdown_frontmatter_raw += yaml.dump(
                markdown_frontmatter,
                allow_unicode=True,
                indent=4,
                default_flow_style=False,
            )
            markdown_frontmatter_raw += "---\n\n"

            markdown_content = markdown_frontmatter_raw + markdown_content.strip()

            markdown_filename = to / (
                template_name + ("." + lang if lang else "") + ".md"
            )

            with open(markdown_filename, "w") as markdown_file:
                markdown_file.write(markdown_content)

            click.echo(f"Markdown file wrote to {markdown_filename} successfully")
    except Exception as e:
        click.secho(
            f"Error while processing archive: {e}", err=True, fg="red", bold=True
        )
        raise


re_title_5 = re.compile(r"(\A|\r?\n)##### (.+)(\r?\n|\Z)")
re_title_4 = re.compile(r"(\A|\r?\n)#### (.+)(\r?\n|\Z)")
re_title_3 = re.compile(r"(\A|\r?\n)### (.+)(\r?\n|\Z)")
re_title_2 = re.compile(r"(\A|\r?\n)## (.+)(\r?\n|\Z)")
re_title_1 = re.compile(r"(\A|\r?\n)# (.+)(\r?\n|\Z)")

re_title_2_long = re.compile(r"(\A|\r?\n)(.+)\r?\n-{2,}(\r?\n|\Z)")
re_title_1_long = re.compile(r"(\A|\r?\n)(.+)\r?\n(={2,})(\r?\n|\Z)")


def shift_markdown_headers(markdown_source):
    '''
    Shifts headers in Markdown so that 1st level became 2nd, 2nd became 3rd, and so on.

    >>> shift_markdown_headers("# Head")
    '## Head'


    >>> shift_markdown_headers("""
    ... # Header 1
    ... 
    ... Lorem ipsum
    ...
    ... ## Header 2
    ...
    ... Lorem ipsum
    ...
    ... Dolor sit
    ...
    ... ##### Header 5
    ...
    ... ###### Header 6
    ... """)
    '\\n## Header 1\\n\\nLorem ipsum\\n\\n### Header 2\\n\\nLorem ipsum\\n\\nDolor sit\\n\\n###### Header 5\\n\\n###### Header 6\\n'

    >>> shift_markdown_headers("""
    ... Header 1
    ... ========
    ...
    ... Header 2
    ... --------
    ... """)
    '\\nHeader 1\\n--------\\n\\n### Header 2\\n'
    '''
    markdown_source = re_title_5.sub(r"\1###### \2\3", markdown_source)
    markdown_source = re_title_4.sub(r"\1##### \2\3", markdown_source)
    markdown_source = re_title_3.sub(r"\1#### \2\3", markdown_source)
    markdown_source = re_title_2.sub(r"\1### \2\3", markdown_source)
    markdown_source = re_title_1.sub(r"\1## \2\3", markdown_source)

    markdown_source = re_title_2_long.sub(r"\1### \2\3", markdown_source)

    def repl_title_1_long(match):
        return (
            match.group(1)
            + match.group(2)
            + "\n"
            + "-" * len(match.group(3))
            + match.group(4)
        )

    markdown_source = re_title_1_long.sub(repl_title_1_long, markdown_source)

    return markdown_source


re_image = re.compile(r"!\[([^\]]+)\]\(([^\)]+)\)")
downloaded_images = {}


def download_and_replace_markdown_images(markdown_source, to):
    slugify = UniqueSlugify(to_lower=True)

    def repl_and_download_image(match):
        image_alt = match.group(1)
        image_url = match.group(2)

        if not image_url.startswith("http://") and not image_url.startswith("https://"):
            if image_url.startswith("/"):
                image_url = "https://zestedesavoir.com" + image_url
            else:
                click.echos(
                    f"Skipping image download for {image_url} (don't know where to fetch it).",
                    err=True,
                )

        click.echo(f"Downloading and replacing image {image_alt} from {image_url}…")

        r = requests.get(image_url, stream=True)
        if not r.ok:
            click.secho("Unable to download image, skipping", err=True, fg="red")
            return match.group(0)

        image = io.BytesIO(r.content)
        image_hash = sha256(image.read()).hexdigest()
        image_ext = "." + image_url.split(".")[-1]

        if image_hash in downloaded_images:
            image_filename = downloaded_images[image_hash]
            image_is_new = False
        else:
            image_filename = slugify(image_alt) + image_ext
            image_is_new = True
            downloaded_images[image_hash] = image_filename

        if image_is_new:
            image.seek(0)
            with open(to / image_filename, "wb") as f:
                shutil.copyfileobj(image, f, length=131072)

        return f"![{image_alt}]({image_filename})"

    return re_image.sub(repl_and_download_image, markdown_source, re.MULTILINE)


def get_content(f):
    return "".join([line for line in io.TextIOWrapper(io.BytesIO(f.read()))]).strip()


if __name__ == "__main__":
    if "--test" in sys.argv:
        import doctest

        doctest.testmod()
    else:
        zds_to_grav()
