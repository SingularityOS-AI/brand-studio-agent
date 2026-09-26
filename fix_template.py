import re

with open("app/tools/brand_soul/template.py", "r") as f:
    content = f.read()

# Fix the {etapa_context} brackets - they need to not be output literally as python `{etapa...}` inside the f-string when it renders, but I put double curly braces so it outputs single curly braces instead of evaluating the python variable!

content = content.replace("{{etapa_context['name']}}", "{etapa_context['name']}")
content = content.replace("{{etapa_context['skill_to_unlock']}}", "{etapa_context['skill_to_unlock']}")
content = content.replace("{{etapa_context['prohibited']}}", "{etapa_context['prohibited']}")
content = content.replace("{{etapa_context['description']}}", "{etapa_context['description']}")

with open("app/tools/brand_soul/template.py", "w") as f:
    f.write(content)
