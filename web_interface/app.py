from flask import Flask, render_template_string, request
from typing import Literal
from stellar_contract_bindings.java import generate_binding as generate_java_binding
from stellar_contract_bindings.python import generate_binding as generate_python_binding
from stellar_contract_bindings.utils import get_specs_by_contract_id
import black

app = Flask(__name__)

required_fields = {
    "java": {
        "package": {"label": "Java Package", "default": "org.example", "type": "text"}
    },
    "python": {},
}


def generate_code(
    contract_id: str,
    rpc_url: str,
    language: str = Literal["python", "java"],
    extra_fields: dict = None,
) -> str:

    specs = get_specs_by_contract_id(contract_id, rpc_url)

    if extra_fields is None:
        extra_fields = {}

    if language == "python":
        code = generate_python_binding(specs, "both")
        return black.format_str(code, mode=black.Mode())
    elif language == "java":
        package = extra_fields.get("package", "org.example")
        code = generate_java_binding(specs, package)
        return code
    else:
        return "Unsupported language selected."


@app.route("/", methods=["GET", "POST"])
def index():
    generated_code = ""
    contract_id = "CDOAW6D7NXAPOCO7TFAWZNJHK62E3IYRGNRVX3VOXNKNVOXCLLPJXQCF"
    rpc_url = "https://mainnet.sorobanrpc.com"
    language = "python"
    extra_fields = {}

    field_values = {}

    if request.method == "POST":
        contract_id = request.form.get("contract_id", "")
        rpc_url = request.form.get("rpc_url", "https://mainnet.sorobanrpc.com")
        language = request.form.get("language", "python")

        if language in required_fields:
            for field_name, field_info in required_fields[language].items():
                field_value = request.form.get(
                    f"{language}_{field_name}", field_info.get("default", "")
                )
                field_values[f"{language}_{field_name}"] = field_value
                extra_fields[field_name] = field_value

        if contract_id:
            generated_code = generate_code(contract_id, rpc_url, language, extra_fields)
    else:
        for lang, fields in required_fields.items():
            for field_name, field_info in fields.items():
                field_values[f"{lang}_{field_name}"] = field_info.get("default", "")

    html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stellar Contract Bindings - Web Generator</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            line-height: 1.6;
        }
        h1 {
            color: #333;
            text-align: center;
        }
        form {
            background-color: #f5f5f5;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: bold;
        }
        input[type="text"], select {
            width: 100%;
            padding: 8px;
            margin-bottom: 15px;
            border: 1px solid #ddd;
            border-radius: 4px;
            box-sizing: border-box;
        }
        button {
            background-color: #4CAF50;
            color: white;
            padding: 10px 15px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
        }
        button:hover {
            background-color: #45a049;
        }
        pre {
            background-color: #f8f8f8;
            border: 1px solid #ddd;
            border-radius: 4px;
            padding: 15px;
            overflow: auto;
            position: relative;
        }
        .copy-button {
            position: absolute;
            top: 5px;
            right: 5px;
            background-color: #333;
            color: white;
            border: none;
            border-radius: 4px;
            padding: 5px 10px;
            cursor: pointer;
        }
        .copy-button:hover {
            background-color: #555;
        }
        .hidden {
            display: none;
        }
        .language-specific-fields {
            padding: 10px;
            margin-top: 10px;
            border-top: 1px solid #ddd;
        }
        footer {
            margin-top: 30px;
            text-align: center;
            font-size: 14px;
            color: #666;
        }
    </style>
</head>
<body>
    <h1>Stellar Contract Bindings Generator</h1>
    
    <form method="POST">
        <div>
            <label for="contract_id">Contract ID:</label>
            <input type="text" id="contract_id" name="contract_id" value="{{ contract_id }}" required>
        </div>
        
        <div>
            <label for="rpc_url">RPC URL:</label>
            <input type="text" id="rpc_url" name="rpc_url" value="{{ rpc_url }}">
        </div>
        
        <div>
            <label for="language">Programming Language:</label>
            <select id="language" name="language" onchange="toggleLanguageSpecificFields()">
                {% for lang in required_fields.keys() %}
                <option value="{{ lang }}" {% if language == lang %}selected{% endif %}>{{ lang|capitalize }}</option>
                {% endfor %}
            </select>
        </div>
        
        {% for lang, fields in required_fields.items() %}
        {% if fields %}
        <div id="{{ lang }}-fields" class="language-specific-fields" style="display: {% if language == lang %}block{% else %}none{% endif %};">
            {% for field_name, field_info in fields.items() %}
            <label for="{{ lang }}_{{ field_name }}">{{ field_info.label }}:</label>
            <input type="{{ field_info.type }}" id="{{ lang }}_{{ field_name }}" name="{{ lang }}_{{ field_name }}" value="{{ field_values.get(lang + '_' + field_name, field_info.default) }}">
            {% endfor %}
        </div>
        {% endif %}
        {% endfor %}
        
        <button type="submit">Generate Code</button>
    </form>
    
    <div id="code-output" class="{% if not generated_code %}hidden{% endif %}">
        <h2>Generated Code:</h2>
        <pre id="code-block"><button class="copy-button" onclick="copyCode()">Copy</button>{{ generated_code }}</pre>
    </div>
    
    <footer>
        This is the web interface for <a href="https://github.com/lightsail-network/stellar-contract-bindings" target="_blank">stellar-contract-bindings</a>.
        Generate client code for Stellar Soroban smart contracts.
    </footer>
    
    <script>
        function toggleLanguageSpecificFields() {
            const language = document.getElementById('language').value;
            
            {% for lang in required_fields.keys() %}
            {% if required_fields[lang] %}
            const {{ lang }}Fields = document.getElementById('{{ lang }}-fields');
            if ({{ lang }}Fields) {
                {{ lang }}Fields.style.display = 'none';
            }
            {% endif %}
            {% endfor %}
            
            const selectedLangFields = document.getElementById(language + '-fields');
            if (selectedLangFields) {
                selectedLangFields.style.display = 'block';
            }
        }
        
        function copyCode() {
            const codeBlock = document.getElementById('code-block');
            const codeText = codeBlock.innerText.replace('Copy', '').trim();
            
            navigator.clipboard.writeText(codeText).then(() => {
                const copyButton = document.querySelector('.copy-button');
                const originalText = copyButton.innerText;
                copyButton.innerText = 'Copied!';
                setTimeout(() => {
                    copyButton.innerText = originalText;
                }, 2000);
            }).catch(err => {
                console.error('Failed to copy: ', err);
            });
        }
    </script>
</body>
</html>
"""
    return render_template_string(
        html,
        contract_id=contract_id,
        rpc_url=rpc_url,
        language=language,
        required_fields=required_fields,
        field_values=field_values,
        generated_code=generated_code,
    )


if __name__ == "__main__":
    app.run(debug=True)
