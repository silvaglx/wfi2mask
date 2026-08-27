# Configuração do Sphinx — documentação do wfi2mask
# Tema: sphinx_rtd_theme (o tema "clássico" do Read the Docs)
# Os arquivos continuam em Markdown, interpretados pelo MyST.

project = "wfi2mask"
author = "Gabriel Lucas"
copyright = "2026, Gabriel Lucas"
release = "0.4.0"
version = release

language = "pt_BR"

extensions = [
    "myst_parser",
    "sphinx_rtd_theme",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "tasklist",
]
myst_heading_anchors = 3

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "requirements.txt"]

html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "collapse_navigation": False,
    "navigation_depth": 3,
    "style_external_links": True,
}
html_context = {
    "display_github": True,
    "github_user": "silvaglx",
    "github_repo": "wfi2mask",
    "github_version": "main",
    "conf_py_path": "/docs/",
}
