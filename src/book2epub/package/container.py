"""OCF META-INF/container.xml generator."""

CONTAINER_XML_CONTENT = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/package.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def generate_container_xml() -> str:
    """Return the static OCF container.xml content."""
    return CONTAINER_XML_CONTENT
