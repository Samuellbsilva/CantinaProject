import os
import sqlite3
import random
import string
import logging
from flask_cors import CORS
from flask import Flask, request, jsonify, g
from datetime import datetime
from functools import wraps
import click
from flask.cli import with_appcontext
from dotenv import load_dotenv

# Configuração do Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app_logger = logging.getLogger(__name__)

# Carrega variáveis do .env (apenas para desenvolvimento local)
load_dotenv() 

# --- Configuração do Aplicativo Flask ---
app = Flask(__name__)

# --- Variáveis de Ambiente e Segurança ---
# Define o ambiente da aplicação: 'production' no Railway, 'development' localmente
FLASK_ENV = os.environ.get("FLASK_ENV", "development") 
app_logger.info(f"Flask environment: {FLASK_ENV}")

# Chave de API de Administração: OBRIGATÓRIO vir de uma variável de ambiente em produção!
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY")

if not ADMIN_API_KEY:
    if FLASK_ENV == "production":
        app_logger.critical("CRITICAL: ADMIN_API_KEY environment variable is not set! Cannot start application securely in production.")
        raise EnvironmentError("ADMIN_API_KEY environment variable is not set! Application cannot start securely.")
    else:
        app_logger.warning("ADMIN_API_KEY not set. Using default key for development ONLY. DO NOT USE IN PRODUCTION.")
        ADMIN_API_KEY = "dev_admin_key_123" # ALTERE ESTA CHAVE PARA UM VALOR DIFERENTE DA CHAVE DE PRODUÇÃO!

# URL da Origem do Frontend (para CORS): OBRIGATÓRIO vir de uma variável de ambiente em produção!
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN")

# Configuração de CORS: Muito importante para segurança!
if FLASK_ENV == "production" and FRONTEND_ORIGIN:
    app_logger.info(f"CORS restricted to origin: {FRONTEND_ORIGIN}")
    CORS(app, resources={r"/*": {"origins": [FRONTEND_ORIGIN]}})
elif FLASK_ENV == "production" and not FRONTEND_ORIGIN:
    app_logger.critical("CRITICAL: FRONTEND_ORIGIN environment variable is not set in production. CORS might be too permissive or break.")
    CORS(app) # Permissivo se FRONTEND_ORIGIN não for definida em produção (NÃO IDEAL!)
else:
    app_logger.info("CORS is permissive (development mode).")
    CORS(app) 

# Caminho do banco de dados SQLite (também pode ser de uma variável de ambiente se precisar de persistência específica no Railway)
DATABASE = os.environ.get("DATABASE_PATH", "cantina.db")
app_logger.info(f"Using database: {DATABASE}")

# --- Funções de Banco de Dados ---

def get_db_connection():
    """Conecta ao banco de dados específico da aplicação (g).
    Cria uma nova conexão se uma não estiver disponível para o contexto atual.
    """
    if 'db_conn' not in g:
        g.db_conn = sqlite3.connect(
            DATABASE,
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db_conn.row_factory = sqlite3.Row # Permite acessar colunas por nome
    return g.db_conn

@app.teardown_appcontext
def close_db_connection(exception=None):
    """Fecha a conexão com o banco de dados ao final da requisição."""
    db_conn = g.pop('db_conn', None)
    if db_conn is not None:
        db_conn.close()

def init_db_logic():
    """Lógica de inicialização do banco de dados (criação de tabelas)."""
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            descricao TEXT,
            preco REAL NOT NULL,
            categoria TEXT DEFAULT 'Geral',
            imagem_url TEXT,
            disponivel BOOLEAN DEFAULT TRUE
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pedidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_identificador TEXT,
            codigo_retirada TEXT NOT NULL UNIQUE,
            data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'PENDENTE' CHECK(status IN ('PENDENTE', 'PREPARANDO', 'PRONTO', 'ENTREGUE', 'CANCELADO')),
            valor_total REAL NOT NULL
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS itens_pedido (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pedido_id INTEGER NOT NULL,
            produto_id INTEGER NOT NULL,
            quantidade INTEGER NOT NULL,
            preco_unitario_compra REAL NOT NULL,
            FOREIGN KEY (pedido_id) REFERENCES pedidos (id),
            FOREIGN KEY (produto_id) REFERENCES produtos (id),
            UNIQUE (pedido_id, produto_id)
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE
        );
    """)
    db.commit()
    app_logger.info("Database schema initialized/checked.")

@app.cli.command('init-db')
@with_appcontext
def init_db_command():
    """Limpa os dados existentes e cria novas tabelas."""
    init_db_logic()
    click.echo('Banco de dados inicializado.')
    app_logger.info("CLI command 'init-db' executed.")

# --- Decorador de Autenticação para Admin ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-KEY')
        if api_key and api_key == ADMIN_API_KEY:
            return f(*args, **kwargs)
        else:
            app_logger.warning(f"Unauthorized admin access attempt from {request.remote_addr}")
            return jsonify({"erro": "Acesso não autorizado. Chave de API inválida ou ausente."}), 401
    return decorated_function

# --- Funções Auxiliares ---
def gerar_codigo_retirada(tamanho=7):
    caracteres = string.ascii_uppercase + string.digits
    while True:
        codigo = ''.join(random.choice(caracteres) for _ in range(tamanho))
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("SELECT id FROM pedidos WHERE codigo_retirada = ?", (codigo,))
        if cursor.fetchone() is None:
            return codigo

# --- ROTAS DE ADMINISTRAÇÃO ---

# --- Gerenciamento de Produtos (Admin) ---
@app.route('/admin/produtos', methods=['POST'])
@admin_required
def admin_adicionar_produto():
    try:
        dados = request.get_json()
        if not dados or 'nome' not in dados or 'preco' not in dados:
            return jsonify({"erro": "Dados incompletos. 'nome' e 'preco' são obrigatórios."}), 400

        nome = dados['nome'].strip()
        descricao = dados.get('descricao', '').strip()
        preco = float(dados['preco'])
        categoria = dados.get('categoria', 'Geral').strip()
        imagem_url = dados.get('imagem_url', None)
        if imagem_url: imagem_url = imagem_url.strip()
        disponivel = bool(dados.get('disponivel', True))

        if preco <= 0:
            return jsonify({"erro": "O preço deve ser um valor positivo."}), 400

        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("INSERT INTO produtos (nome, descricao, preco, categoria, imagem_url, disponivel) VALUES (?, ?, ?, ?, ?, ?)",
                       (nome, descricao, preco, categoria, imagem_url, disponivel))
        db.commit()
        produto_id = cursor.lastrowid
        return jsonify({"id": produto_id, "nome": nome, "descricao": descricao, "preco": preco, "categoria": categoria, "imagem_url": imagem_url, "disponivel": disponivel}), 201
    except ValueError:
        app_logger.error(f"Valor inválido no formulário de produto: {request.get_json()}")
        return jsonify({"erro": "Formato de preço inválido ou dados malformados."}), 400
    except Exception as e:
        app_logger.error(f"Erro interno ao adicionar produto: {str(e)}", exc_info=True)
        return jsonify({"erro": "Ocorreu um erro interno no servidor." if FLASK_ENV == "production" else f"Erro interno: {str(e)}"}), 500

@app.route('/admin/produtos', methods=['GET'])
@admin_required
def admin_listar_todos_produtos():
    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("SELECT id, nome, descricao, preco, categoria, imagem_url, disponivel FROM produtos")
        produtos = [dict(row) for row in cursor.fetchall()]
        return jsonify(produtos), 200
    except Exception as e:
        app_logger.error(f"Erro interno ao listar produtos (admin): {str(e)}", exc_info=True)
        return jsonify({"erro": "Ocorreu um erro interno no servidor." if FLASK_ENV == "production" else f"Erro interno ao listar produtos (admin): {str(e)}"}), 500

@app.route('/admin/produtos/<int:produto_id>', methods=['PUT'])
@admin_required
def admin_atualizar_produto(produto_id):
    try:
        dados = request.get_json()
        if not dados:
            return jsonify({"erro": "Nenhum dado fornecido para atualização."}), 400

        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("SELECT id FROM produtos WHERE id = ?", (produto_id,))
        if not cursor.fetchone():
            return jsonify({"erro": "Produto não encontrado."}), 404

        campos_para_atualizar = []
        valores_para_atualizar = []

        if 'nome' in dados:
            campos_para_atualizar.append("nome = ?")
            valores_para_atualizar.append(dados['nome'].strip())
        if 'descricao' in dados:
            campos_para_atualizar.append("descricao = ?")
            valores_para_atualizar.append(dados['descricao'].strip())
        if 'preco' in dados:
            preco = float(dados['preco'])
            if preco <= 0:
                return jsonify({"erro": "O preço deve ser um valor positivo."}), 400
            campos_para_atualizar.append("preco = ?")
            valores_para_atualizar.append(preco)
        if 'categoria' in dados:
            campos_para_atualizar.append("categoria = ?")
            valores_para_atualizar.append(dados['categoria'].strip())
        if 'imagem_url' in dados:
            campos_para_atualizar.append("imagem_url = ?")
            valores_para_atualizar.append(dados['imagem_url'].strip() if dados['imagem_url'] else None)
        if 'disponivel' in dados:
            campos_para_atualizar.append("disponivel = ?")
            valores_para_atualizar.append(bool(dados['disponivel']))

        if not campos_para_atualizar:
            return jsonify({"erro": "Nenhum campo válido fornecido para atualização."}), 400

        valores_para_atualizar.append(produto_id)
        query = f"UPDATE produtos SET {', '.join(campos_para_atualizar)} WHERE id = ?"
        cursor.execute(query, tuple(valores_para_atualizar))
        db.commit()

        cursor.execute("SELECT id, nome, descricao, preco, categoria, imagem_url, disponivel FROM produtos WHERE id = ?", (produto_id,))
        produto_atualizado = dict(cursor.fetchone())
        return jsonify(produto_atualizado), 200
    except ValueError:
        app_logger.error(f"Valor inválido na atualização de produto: {request.get_json()}")
        return jsonify({"erro": "Formato de preço inválido ou dados malformados."}), 400
    except Exception as e:
        app_logger.error(f"Erro interno ao atualizar produto {produto_id}: {str(e)}", exc_info=True)
        return jsonify({"erro": "Ocorreu um erro interno no servidor." if FLASK_ENV == "production" else f"Erro interno ao atualizar produto: {str(e)}"}), 500

@app.route('/admin/produtos/<int:produto_id>', methods=['DELETE'])
@admin_required
def admin_deletar_produto(produto_id):
    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("SELECT id, nome FROM produtos WHERE id = ?", (produto_id,))
        produto = cursor.fetchone()
        if not produto:
            return jsonify({"erro": "Produto não encontrado."}), 404
        
        # Verificar se o produto está associado a algum item de pedido
        cursor.execute("SELECT COUNT(*) as count FROM itens_pedido WHERE produto_id = ?", (produto_id,))
        if cursor.fetchone()['count'] > 0:
            return jsonify({"erro": f"Produto '{produto['nome']}' não pode ser deletado, pois está associado a pedidos existentes. Considere torná-lo indisponível."}), 409 # Conflict

        cursor.execute("DELETE FROM produtos WHERE id = ?", (produto_id,))
        db.commit()
        return jsonify({"mensagem": f"Produto '{produto['nome']}' deletado com sucesso."}), 200
    except sqlite3.IntegrityError:
        app_logger.error(f"Erro de integridade ao tentar deletar produto {produto_id}. Referência em pedidos.")
        return jsonify({"erro": "Erro de integridade: Produto pode estar referenciado em pedidos. Tente torná-lo indisponível."}), 409
    except Exception as e:
        app_logger.error(f"Erro interno ao deletar produto {produto_id}: {str(e)}", exc_info=True)
        return jsonify({"erro": "Ocorreu um erro interno no servidor." if FLASK_ENV == "production" else f"Erro interno ao deletar produto: {str(e)}"}), 500

# --- Gerenciamento de Pedidos (Admin) ---
@app.route('/admin/relatorios/ganhos', methods=['GET'])
@admin_required
def admin_relatorio_ganhos_diarios():
    try:
        data_str = request.args.get('data', datetime.now().strftime('%Y-%m-%d'))
        try:
            data_obj = datetime.strptime(data_str, '%Y-%m-%d')
        except ValueError:
            return jsonify({"erro": "Formato de data inválido. Use AAAA-MM-DD."}), 400

        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("""
            SELECT SUM(valor_total) as total_ganhos, COUNT(id) as quantidade_pedidos
            FROM pedidos
            WHERE DATE(data_hora) = DATE(?) AND status != 'CANCELADO'
        """, (data_obj.strftime('%Y-%m-%d'),))

        resultado = cursor.fetchone()
        total_ganhos = resultado['total_ganhos'] if resultado['total_ganhos'] is not None else 0
        quantidade_pedidos = resultado['quantidade_pedidos'] if resultado['quantidade_pedidos'] is not None else 0

        return jsonify({
            "data_consulta": data_obj.strftime('%Y-%m-%d'),
            "total_ganhos": total_ganhos,
            "quantidade_pedidos_no_dia": quantidade_pedidos
        }), 200
    except Exception as e:
        app_logger.error(f"Erro interno ao gerar relatório de ganhos para data {data_str}: {str(e)}", exc_info=True)
        return jsonify({"erro": "Ocorreu um erro interno no servidor." if FLASK_ENV == "production" else f"Erro interno ao gerar relatório de ganhos: {str(e)}"}), 500

@app.route('/admin/pedidos', methods=['GET'])
@admin_required
def admin_listar_todos_pedidos():
    try:
        limit = request.args.get('limit', type=int)
        db = get_db_connection()
        cursor = db.cursor()
        
        query = "SELECT id, cliente_identificador, codigo_retirada, data_hora, status, valor_total FROM pedidos ORDER BY data_hora DESC"
        if limit and limit > 0:
            query += f" LIMIT {limit}"

        cursor.execute(query)
        pedidos_db = cursor.fetchall()
        pedidos = []
        for pedido_row in pedidos_db:
            pedido_dict = dict(pedido_row)
            itens_cursor = db.cursor()
            itens_cursor.execute("""
                SELECT p.nome as produto_nome, ip.quantidade, ip.preco_unitario_compra
                FROM itens_pedido ip
                JOIN produtos p ON ip.produto_id = p.id
                WHERE ip.pedido_id = ?
            """, (pedido_dict['id'],))
            itens = [dict(item_row) for item_row in itens_cursor.fetchall()]
            pedido_dict['itens'] = itens
            pedidos.append(pedido_dict)
        return jsonify(pedidos), 200
    except Exception as e:
        app_logger.error(f"Erro interno ao listar todos os pedidos (admin): {str(e)}", exc_info=True)
        return jsonify({"erro": "Ocorreu um erro interno no servidor." if FLASK_ENV == "production" else f"Erro interno ao listar todos os pedidos (admin): {str(e)}"}), 500

@app.route('/admin/pedidos/<string:codigo_retirada>/status', methods=['PUT'])
@admin_required
def admin_atualizar_status_pedido(codigo_retirada):
    try:
        dados = request.get_json()
        if not dados or 'status' not in dados:
            return jsonify({"erro": "Novo 'status' é obrigatório."}), 400

        novo_status = dados['status'].upper()
        status_permitidos = ['PENDENTE', 'PREPARANDO', 'PRONTO', 'ENTREGUE', 'CANCELADO']
        if novo_status not in status_permitidos:
            return jsonify({"erro": f"Status inválido. Permitidos: {', '.join(status_permitidos)}"}), 400

        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("SELECT id FROM pedidos WHERE codigo_retirada = ?", (codigo_retirada,))
        pedido = cursor.fetchone()

        if not pedido:
            return jsonify({"erro": "Pedido não encontrado com este código de retirada."}), 404

        cursor.execute("UPDATE pedidos SET status = ? WHERE codigo_retirada = ?", (novo_status, codigo_retirada))
        db.commit()
        return jsonify({"mensagem": f"Status do pedido {codigo_retirada} atualizado para {novo_status}."}), 200
    except Exception as e:
        app_logger.error(f"Erro interno ao atualizar status do pedido {codigo_retirada}: {str(e)}", exc_info=True)
        return jsonify({"erro": "Ocorreu um erro interno no servidor." if FLASK_ENV == "production" else f"Erro interno ao atualizar status do pedido: {str(e)}"}), 500

# --- ROTAS PÚBLICAS / CLIENTE ---

@app.route('/produtos', methods=['GET'])
def cliente_listar_produtos():
    try:
        categoria_filtro = request.args.get('categoria', None)
        termo_busca = request.args.get('busca', None)

        query = "SELECT id, nome, descricao, preco, categoria, imagem_url, disponivel FROM produtos WHERE disponivel = TRUE"
        params = []

        if categoria_filtro:
            query += " AND lower(categoria) = lower(?)"
            params.append(categoria_filtro.strip())
        if termo_busca:
            query += " AND (lower(nome) LIKE lower(?) OR lower(descricao) LIKE lower(?))"
            params.append(f"%{termo_busca.strip()}%")
            params.append(f"%{termo_busca.strip()}%")

        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute(query, tuple(params))
        produtos = [dict(row) for row in cursor.fetchall()]
        return jsonify(produtos), 200
    except Exception as e:
        app_logger.error(f"Erro interno ao listar produtos (cliente): {str(e)}", exc_info=True)
        return jsonify({"erro": "Ocorreu um erro interno no servidor." if FLASK_ENV == "production" else f"Erro interno ao listar produtos (cliente): {str(e)}"}), 500

@app.route('/produtos/<int:produto_id>', methods=['GET'])
def cliente_obter_produto(produto_id):
    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("SELECT id, nome, descricao, preco, categoria, imagem_url, disponivel FROM produtos WHERE id = ? AND disponivel = TRUE", (produto_id,))
        produto = cursor.fetchone()
        if produto:
            return jsonify(dict(produto)), 200
        else:
            return jsonify({"erro": "Produto não encontrado ou indisponível."}), 404
    except Exception as e:
        app_logger.error(f"Erro interno ao obter produto {produto_id} (cliente): {str(e)}", exc_info=True)
        return jsonify({"erro": "Ocorreu um erro interno no servidor." if FLASK_ENV == "production" else f"Erro interno ao obter produto (cliente): {str(e)}"}), 500

@app.route('/pedidos', methods=['POST'])
def cliente_criar_pedido():
    try:
        dados = request.get_json()
        if not dados or 'itens' not in dados or not isinstance(dados['itens'], list) or not dados['itens']:
            return jsonify({"erro": "Dados incompletos ou formato inválido. 'itens' (lista não vazia) é obrigatório."}), 400

        cliente_id = dados.get('cliente_identificador', None) 
        if cliente_id: cliente_id = str(cliente_id).strip()

        itens_pedido_info = []
        valor_total_pedido = 0.0

        db = get_db_connection()
        cursor = db.cursor()

        # Validação e coleta dos itens do pedido
        for item_req in dados['itens']:
            if 'produto_id' not in item_req or 'quantidade' not in item_req:
                return jsonify({"erro": "Cada item deve ter 'produto_id' e 'quantidade'."}), 400

            try:
                produto_id = int(item_req['produto_id'])
                quantidade = int(item_req['quantidade'])
            except ValueError:
                return jsonify({"erro": "Produto ID e quantidade devem ser números inteiros."}), 400

            if quantidade <= 0:
                return jsonify({"erro": f"Quantidade inválida para o produto ID {produto_id}. Deve ser maior que zero."}), 400

            cursor.execute("SELECT id, nome, preco, disponivel FROM produtos WHERE id = ?", (produto_id,))
            produto_db = cursor.fetchone()

            if not produto_db:
                return jsonify({"erro": f"Produto com ID {produto_id} não encontrado."}), 404
            if not produto_db['disponivel']:
                return jsonify({"erro": f"Produto '{produto_db['nome']}' (ID: {produto_id}) não está disponível."}), 400

            preco_unitario_compra = float(produto_db['preco'])
            itens_pedido_info.append({
                "produto_id": produto_id,
                "quantidade": quantidade,
                "preco_unitario_compra": preco_unitario_compra
            })
            valor_total_pedido += quantidade * preco_unitario_compra

        if valor_total_pedido <= 0:
            return jsonify({"erro": "O valor total do pedido deve ser positivo."}), 400

        # Cria o pedido principal
        codigo_retirada_gerado = gerar_codigo_retirada()
        cursor.execute("INSERT INTO pedidos (cliente_identificador, codigo_retirada, valor_total) VALUES (?, ?, ?)",
                       (cliente_id, codigo_retirada_gerado, valor_total_pedido))
        pedido_id = cursor.lastrowid

        # Insere os itens do pedido
        for item in itens_pedido_info:
            cursor.execute("INSERT INTO itens_pedido (pedido_id, produto_id, quantidade, preco_unitario_compra) VALUES (?, ?, ?, ?)",
                           (pedido_id, item['produto_id'], item['quantidade'], item['preco_unitario_compra']))
        db.commit()

        return jsonify({
            "mensagem": "Pedido realizado com sucesso!",
            "pedido_id": pedido_id,
            "codigo_retirada": codigo_retirada_gerado,
            "valor_total": valor_total_pedido,
            "status": "PENDENTE"
        }), 201

    except ValueError as ve:
        app_logger.error(f"Valor inválido nos dados do pedido: {str(ve)}", exc_info=True)
        return jsonify({"erro": f"Valor inválido nos dados do pedido: {str(ve)}"}), 400
    except Exception as e:
        db = g.get('db_conn', None)
        if db:
            db.rollback() 
        app_logger.error(f"Erro interno ao criar pedido: {str(e)}", exc_info=True)
        return jsonify({"erro": "Ocorreu um erro interno no servidor." if FLASK_ENV == "production" else f"Erro interno ao criar pedido: {str(e)}"}), 500

@app.route('/pedidos/<string:codigo_retirada>', methods=['GET'])
def cliente_consultar_pedido(codigo_retirada):
    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("SELECT id, cliente_identificador, codigo_retirada, data_hora, status, valor_total FROM pedidos WHERE codigo_retirada = ?", (codigo_retirada,))
        pedido = cursor.fetchone()

        if not pedido:
            return jsonify({"erro": "Pedido não encontrado com este código de retirada."}), 404

        pedido_dict = dict(pedido)
        
        itens_cursor = db.cursor()
        itens_cursor.execute("""
            SELECT ip.produto_id, p.nome as produto_nome, ip.quantidade, ip.preco_unitario_compra
            FROM itens_pedido ip
            JOIN produtos p ON ip.produto_id = p.id
            WHERE ip.pedido_id = ?
        """, (pedido_dict['id'],))
        itens = [dict(row) for row in itens_cursor.fetchall()]
        pedido_dict['itens'] = itens
        return jsonify(pedido_dict), 200
    except Exception as e:
        app_logger.error(f"Erro interno ao consultar pedido (cliente) {codigo_retirada}: {str(e)}", exc_info=True)
        return jsonify({"erro": "Ocorreu um erro interno no servidor." if FLASK_ENV == "production" else f"Erro interno ao consultar pedido (cliente): {str(e)}"}), 500

@app.route('/meus-pedidos/<string:cliente_id>', methods=['GET'])
def cliente_listar_meus_pedidos(cliente_id):
    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("""
            SELECT id, codigo_retirada, data_hora, status, valor_total 
            FROM pedidos 
            WHERE cliente_identificador = ? 
            ORDER BY data_hora DESC
        """, (cliente_id,))
        
        pedidos_db = cursor.fetchall()
        pedidos = []
        if not pedidos_db:
            return jsonify([]), 200 

        for pedido_row in pedidos_db:
            pedido_dict = dict(pedido_row)
            itens_cursor = db.cursor()
            itens_cursor.execute("""
                SELECT p.nome as produto_nome, ip.quantidade, ip.preco_unitario_compra
                FROM itens_pedido ip
                JOIN produtos p ON ip.produto_id = p.id
                WHERE ip.pedido_id = ?
            """, (pedido_dict['id'],))
            itens = [dict(item_row) for item_row in itens_cursor.fetchall()]
            pedido_dict['itens'] = itens
            pedidos.append(pedido_dict)
        return jsonify(pedidos), 200
    except Exception as e:
        app_logger.error(f"Erro interno ao listar pedidos do cliente {cliente_id}: {str(e)}", exc_info=True)
        return jsonify({"erro": "Ocorreu um erro interno no servidor." if FLASK_ENV == "production" else f"Erro interno ao listar seus pedidos: {str(e)}"}), 500

# --- Inicialização ---
if __name__ == '__main__':
    # Este bloco de código só é executado quando você roda o script diretamente (ex: python app.py).
    # Em ambientes de produção como o Railway, um servidor WSGI (como Gunicorn) será usado,
    # e ele não executa este bloco.
    if FLASK_ENV != "production":
        with app.app_context():
            init_db_logic() # Inicializa o DB localmente se não for ambiente de produção
        app_logger.info(f"Running in {FLASK_ENV} mode. Debug: True")
        app.run(debug=True, port=5000) # Porta padrão para Flask
    else:
        app_logger.info("Server is running in production mode via WSGI server (e.g., Gunicorn).")
