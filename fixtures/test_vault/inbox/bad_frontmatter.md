---
title: "Unclosed title string
tags: [broken, syntax
  random:	tabs: here
---

# Malformed Frontmatter Note

Even though the YAML front matter above is invalid, the parser must recover gracefully.
The note should still be indexed, its body content searchable, and the parse error recorded in `notes.parse_error`.

## Searchable Section

Content in this section discusses fault tolerance and error handling.
Tag inline: #resilience.
