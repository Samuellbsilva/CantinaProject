import sqlite3
import random
import string
from flask_cors import CORS
import flask # Importando Flask e outras dependências
from flask import Flask, request, jsonify
from datetime import datetime
from functools import wraps # Para o decorador de autenticação

# --- Configuração do Aplicativo Flask ---
app = Flask(__name__)
DATABASE = 'cantina.db'

# !!! ADICIONE SUA CHAVE DE API DE ADMINISTRAÇÃO AQUI !!!
# Em um ambiente de produção, isso viria de uma variável de ambiente ou arquivo de configuração seguro.
ADMIN_API_KEY = "SUA_CHAVE_SECRETA_DE_ADMIN"

# --- Funções de Banco de Dados ---
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row # Permite acessar colunas por nome
    return conn

def init_db():
    db = get_db()
    cursor = db.cursor()
    # Adicionando campo 'categoria' e 'imagem_url' à tabela produtos
    # Adicionando campo 'cliente_identificador' à tabela pedidos (opcional para rastreio simples)
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
            cliente_identificador TEXT, -- Opcional: para o cliente ver seus pedidos depois
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
            FOREIGN KEY (produto_id) REFERENCES produtos (id)
        );
    """)
    # Tabela para Categorias (Opcional, mas bom para organização)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE
        );
    """)
    db.commit()
    db.close()

# --- Decorador de Autenticação para Admin ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-KEY')
        if api_key and api_key == ADMIN_API_KEY:
            return f(*args, **kwargs)
        else:
            return jsonify({"erro": "Acesso não autorizado. Chave de API inválida ou ausente."}), 401
    return decorated_function

# --- Funções Auxiliares ---
def gerar_codigo_retirada(tamanho=7):
    caracteres = string.ascii_uppercase + string.digits
    while True:
        codigo = ''.join(random.choice(caracteres) for _ in range(tamanho))
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT id FROM pedidos WHERE codigo_retirada = ?", (codigo,))
        if cursor.fetchone() is None:
            db.close()
            return codigo
        db.close()

# --- ROTAS DE ADMINISTRAÇÃO ---




# --- Gerenciamento de Produtos (Admin) ---
@app.route('/admin/produtos', methods=['POST'])
@admin_required
def admin_adicionar_produto():
    try:
        dados = request.get_json()
        if not dados or 'nome' not in dados or 'preco' not in dados:
            return jsonify({"erro": "Dados incompletos. 'nome' e 'preco' são obrigatórios."}), 400

        nome = dados['nome']
        descricao = dados.get('descricao', '')
        preco = float(dados['preco'])
        categoria = dados.get('categoria', 'Geral')
        imagem_url = dados.get('imagem_url', None)
        disponivel = dados.get('disponivel', True)

        if preco <= 0:
            return jsonify({"erro": "O preço deve ser um valor positivo."}), 400

        db = get_db()
        cursor = db.cursor()
        cursor.execute("INSERT INTO produtos (nome, descricao, preco, categoria, imagem_url, disponivel) VALUES (?, ?, ?, ?, ?, ?)",
                       (nome, descricao, preco, categoria, imagem_url, disponivel))
        db.commit()
        produto_id = cursor.lastrowid
        db.close()
        return jsonify({"id": produto_id, "nome": nome, "descricao": descricao, "preco": preco, "categoria": categoria, "imagem_url": imagem_url, "disponivel": disponivel}), 201
    except ValueError:
        return jsonify({"erro": "Formato de preço inválido."}), 400
    except Exception as e:
        return jsonify({"erro": f"Erro interno ao adicionar produto: {str(e)}"}), 500

@app.route('/admin/produtos', methods=['GET'])
@admin_required
def admin_listar_todos_produtos():
    # Admin vê todos os produtos, disponíveis ou não
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT id, nome, descricao, preco, categoria, imagem_url, disponivel FROM produtos")
        produtos = [dict(row) for row in cursor.fetchall()]
        db.close()
        return jsonify(produtos), 200
    except Exception as e:
        return jsonify({"erro": f"Erro interno ao listar produtos (admin): {str(e)}"}), 500

@app.route('/admin/produtos/<int:produto_id>', methods=['PUT'])
@admin_required
def admin_atualizar_produto(produto_id):
    try:
        dados = request.get_json()
        if not dados:
            return jsonify({"erro": "Nenhum dado fornecido para atualização."}), 400

        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT id FROM produtos WHERE id = ?", (produto_id,))
        if not cursor.fetchone():
            db.close()
            return jsonify({"erro": "Produto não encontrado."}), 404

        campos_para_atualizar = []
        valores_para_atualizar = []

        if 'nome' in dados:
            campos_para_atualizar.append("nome = ?")
            valores_para_atualizar.append(dados['nome'])
        if 'descricao' in dados:
            campos_para_atualizar.append("descricao = ?")
            valores_para_atualizar.append(dados['descricao'])
        if 'preco' in dados:
            preco = float(dados['preco'])
            if preco <= 0:
                db.close()
                return jsonify({"erro": "O preço deve ser um valor positivo."}), 400
            campos_para_atualizar.append("preco = ?")
            valores_para_atualizar.append(preco)
        if 'categoria' in dados:
            campos_para_atualizar.append("categoria = ?")
            valores_para_atualizar.append(dados['categoria'])
        if 'imagem_url' in dados:
            campos_para_atualizar.append("imagem_url = ?")
            valores_para_atualizar.append(dados['imagem_url'])
        if 'disponivel' in dados:
            campos_para_atualizar.append("disponivel = ?")
            valores_para_atualizar.append(bool(dados['disponivel']))

        if not campos_para_atualizar:
            db.close()
            return jsonify({"erro": "Nenhum campo válido fornecido para atualização."}), 400

        valores_para_atualizar.append(produto_id)
        query = f"UPDATE produtos SET {', '.join(campos_para_atualizar)} WHERE id = ?"
        cursor.execute(query, tuple(valores_para_atualizar))
        db.commit()

        cursor.execute("SELECT id, nome, descricao, preco, categoria, imagem_url, disponivel FROM produtos WHERE id = ?", (produto_id,))
        produto_atualizado = dict(cursor.fetchone())
        db.close()
        return jsonify(produto_atualizado), 200
    except ValueError:
        return jsonify({"erro": "Formato de preço inválido."}), 400
    except Exception as e:
        return jsonify({"erro": f"Erro interno ao atualizar produto: {str(e)}"}), 500

@app.route('/admin/produtos/<int:produto_id>', methods=['DELETE'])
@admin_required
def admin_deletar_produto(produto_id):
    try:
        db = get_db()
        cursor = db.cursor()
        # Verificar se o produto existe
        cursor.execute("SELECT id FROM produtos WHERE id = ?", (produto_id,))
        if not cursor.fetchone():
            db.close()
            return jsonify({"erro": "Produto não encontrado."}), 404
        
        # Opcional: Verificar se o produto está em itens_pedido antes de deletar
        # para evitar erro de integridade ou decidir por deleção lógica.
        cursor.execute("SELECT COUNT(*) as count FROM itens_pedido WHERE produto_id = ?", (produto_id,))
        if cursor.fetchone()['count'] > 0:
            # Opção 1: Não permitir deletar
            # db.close()
            # return jsonify({"erro": "Produto não pode ser deletado, pois está associado a pedidos. Considere torná-lo indisponível."}), 409 # Conflict

            # Opção 2: Deleção Lógica (marcar como indisponível) - já feito no PUT
            # Se for deleção física, o SQLite pode dar erro se houver FK constraint sem ON DELETE CASCADE
            pass # Prossegue com a deleção física por agora

        cursor.execute("DELETE FROM produtos WHERE id = ?", (produto_id,))
        db.commit()
        db.close()
        return jsonify({"mensagem": "Produto deletado com sucesso."}), 200
    except sqlite3.IntegrityError:
         return jsonify({"erro": "Erro de integridade: Produto pode estar referenciado em pedidos."}), 409
    except Exception as e:
        return jsonify({"erro": f"Erro interno ao deletar produto: {str(e)}"}), 500

# --- Gerenciamento de Pedidos (Admin) ---
@app.route('/admin/relatorios/ganhos', methods=['GET'])
@admin_required
def admin_relatorio_ganhos_diarios():
    try:
        # Pega a data de hoje por padrão, ou uma data específica via query param
        data_str = request.args.get('data', datetime.now().strftime('%Y-%m-%d'))
        try:
            data_obj = datetime.strptime(data_str, '%Y-%m-%d')
        except ValueError:
            return jsonify({"erro": "Formato de data inválido. Use YYYY-MM-DD."}), 400

        db = get_db()
        cursor = db.cursor()

        # Considerar apenas pedidos 'ENTREGUE' ou 'PRONTO' para o ganho?
        # Ou todos os pedidos do dia, independentemente do status?
        # Vou considerar todos os 'PENDENTE', 'PREPARANDO', 'PRONTO', 'ENTREGUE'
        # Excluindo 'CANCELADO'
        cursor.execute("""
            SELECT SUM(valor_total) as total_ganhos, COUNT(id) as quantidade_pedidos
            FROM pedidos
            WHERE DATE(data_hora) = DATE(?) AND status != 'CANCELADO'
        """, (data_obj.strftime('%Y-%m-%d'),)) # Usar DATE() para comparar apenas a data

        resultado = cursor.fetchone()
        db.close()

        total_ganhos = resultado['total_ganhos'] if resultado['total_ganhos'] is not None else 0
        quantidade_pedidos = resultado['quantidade_pedidos'] if resultado['quantidade_pedidos'] is not None else 0

        return jsonify({
            "data_consulta": data_obj.strftime('%Y-%m-%d'),
            "total_ganhos": total_ganhos,
            "quantidade_pedidos_no_dia": quantidade_pedidos
        }), 200
    except Exception as e:
        return jsonify({"erro": f"Erro interno ao gerar relatório de ganhos: {str(e)}"}), 500


@app.route('/admin/pedidos', methods=['GET'])
@admin_required
def admin_listar_todos_pedidos():
    try:
        db = get_db()
        cursor = db.cursor()
        # Ordenar por data/hora mais recente e incluir identificador do cliente se disponível
        cursor.execute("SELECT id, cliente_identificador, codigo_retirada, data_hora, status, valor_total FROM pedidos ORDER BY data_hora DESC")
        pedidos_db = cursor.fetchall()
        pedidos = []
        for pedido_row in pedidos_db:
            pedido_dict = dict(pedido_row)
            cursor.execute("""
                SELECT p.nome as produto_nome, ip.quantidade, ip.preco_unitario_compra
                FROM itens_pedido ip
                JOIN produtos p ON ip.produto_id = p.id
                WHERE ip.pedido_id = ?
            """, (pedido_dict['id'],))
            itens = [dict(item_row) for item_row in cursor.fetchall()]
            pedido_dict['itens'] = itens
            pedidos.append(pedido_dict)
        db.close()
        return jsonify(pedidos), 200
    except Exception as e:
        return jsonify({"erro": f"Erro interno ao listar todos os pedidos (admin): {str(e)}"}), 500

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

        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT id FROM pedidos WHERE codigo_retirada = ?", (codigo_retirada,))
        pedido = cursor.fetchone()

        if not pedido:
            db.close()
            return jsonify({"erro": "Pedido não encontrado com este código de retirada."}), 404

        cursor.execute("UPDATE pedidos SET status = ? WHERE codigo_retirada = ?", (novo_status, codigo_retirada))
        db.commit()
        db.close()
        return jsonify({"mensagem": f"Status do pedido {codigo_retirada} atualizado para {novo_status}."}), 200
    except Exception as e:
        return jsonify({"erro": f"Erro interno ao atualizar status do pedido: {str(e)}"}), 500

# --- ROTAS PÚBLICAS / CLIENTE ---

# --- Visualização de Produtos (Cliente) ---
@app.route('/produtos', methods=['GET']) # ou '/cliente/produtos'
def cliente_listar_produtos():
    try:
        # Clientes veem apenas produtos disponíveis por padrão
        # Adicionar filtro por categoria
        categoria_filtro = request.args.get('categoria', None)
        termo_busca = request.args.get('busca', None)

        query = "SELECT id, nome, descricao, preco, categoria, imagem_url, disponivel FROM produtos WHERE disponivel = TRUE"
        params = []

        if categoria_filtro:
            query += " AND lower(categoria) = lower(?)"
            params.append(categoria_filtro)
        if termo_busca:
            query += " AND (lower(nome) LIKE lower(?) OR lower(descricao) LIKE lower(?))"
            params.append(f"%{termo_busca}%")
            params.append(f"%{termo_busca}%")


        db = get_db()
        cursor = db.cursor()
        cursor.execute(query, tuple(params))
        produtos = [dict(row) for row in cursor.fetchall()]
        db.close()
        return jsonify(produtos), 200
    except Exception as e:
        return jsonify({"erro": f"Erro interno ao listar produtos (cliente): {str(e)}"}), 500

@app.route('/produtos/<int:produto_id>', methods=['GET']) # ou '/cliente/produtos/<int:produto_id>'
def cliente_obter_produto(produto_id):
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT id, nome, descricao, preco, categoria, imagem_url, disponivel FROM produtos WHERE id = ? AND disponivel = TRUE", (produto_id,))
        produto = cursor.fetchone()
        db.close()
        if produto:
            return jsonify(dict(produto)), 200
        else:
            return jsonify({"erro": "Produto não encontrado ou indisponível."}), 404
    except Exception as e:
        return jsonify({"erro": f"Erro interno ao obter produto (cliente): {str(e)}"}), 500

# --- Criação e Consulta de Pedidos (Cliente) ---
@app.route('/pedidos', methods=['POST']) # ou '/cliente/pedidos'
def cliente_criar_pedido():
    db = None
    try:
        dados = request.get_json()
        if not dados or 'itens' not in dados or not isinstance(dados['itens'], list) or not dados['itens']:
            return jsonify({"erro": "Dados incompletos ou formato inválido. 'itens' (lista não vazia) é obrigatório."}), 400

        # Opcional: Obter um identificador do cliente se você quiser associar pedidos a clientes
        cliente_id = dados.get('cliente_identificador', None) # Ex: ID do usuário, email, etc.

        itens_pedido_info = []
        valor_total_pedido = 0.0

        db = get_db()
        cursor = db.cursor()

        for item_req in dados['itens']:
            if 'produto_id' not in item_req or 'quantidade' not in item_req:
                db.close()
                return jsonify({"erro": "Cada item deve ter 'produto_id' e 'quantidade'."}), 400

            produto_id = item_req['produto_id']
            quantidade = int(item_req['quantidade'])

            if quantidade <= 0:
                db.close()
                return jsonify({"erro": f"Quantidade inválida para o produto ID {produto_id}."}), 400

            cursor.execute("SELECT id, nome, preco, disponivel FROM produtos WHERE id = ?", (produto_id,))
            produto_db = cursor.fetchone()

            if not produto_db:
                db.close()
                return jsonify({"erro": f"Produto com ID {produto_id} não encontrado."}), 404
            if not produto_db['disponivel']:
                db.close()
                return jsonify({"erro": f"Produto '{produto_db['nome']}' (ID: {produto_id}) não está disponível."}), 400

            preco_unitario_compra = float(produto_db['preco'])
            itens_pedido_info.append({
                "produto_id": produto_id,
                "quantidade": quantidade,
                "preco_unitario_compra": preco_unitario_compra
            })
            valor_total_pedido += quantidade * preco_unitario_compra

        if valor_total_pedido <= 0:
             db.close()
             return jsonify({"erro": "O valor total do pedido deve ser positivo."}), 400

        codigo_retirada_gerado = gerar_codigo_retirada()

        cursor.execute("INSERT INTO pedidos (cliente_identificador, codigo_retirada, valor_total) VALUES (?, ?, ?)",
                       (cliente_id, codigo_retirada_gerado, valor_total_pedido))
        pedido_id = cursor.lastrowid

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
        return jsonify({"erro": f"Valor inválido nos dados do pedido: {str(ve)}"}), 400
    except Exception as e:
        if db:
            db.rollback()
        return jsonify({"erro": f"Erro interno ao criar pedido: {str(e)}"}), 500
    finally:
        if db:
            db.close()

@app.route('/pedidos/<string:codigo_retirada>', methods=['GET']) # ou '/cliente/pedidos/<codigo_retirada>'
def cliente_consultar_pedido(codigo_retirada):
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT id, cliente_identificador, codigo_retirada, data_hora, status, valor_total FROM pedidos WHERE codigo_retirada = ?", (codigo_retirada,))
        pedido = cursor.fetchone()

        if not pedido:
            db.close()
            return jsonify({"erro": "Pedido não encontrado com este código de retirada."}), 404

        pedido_dict = dict(pedido)
        cursor.execute("""
            SELECT ip.produto_id, p.nome as produto_nome, ip.quantidade, ip.preco_unitario_compra
            FROM itens_pedido ip
            JOIN produtos p ON ip.produto_id = p.id
            WHERE ip.pedido_id = ?
        """, (pedido_dict['id'],))
        itens = [dict(row) for row in cursor.fetchall()]
        pedido_dict['itens'] = itens
        db.close()
        return jsonify(pedido_dict), 200
    except Exception as e:
        return jsonify({"erro": f"Erro interno ao consultar pedido (cliente): {str(e)}"}), 500

# Rota para o cliente ver seus próprios pedidos (se um identificador foi usado)
@app.route('/meus-pedidos/<string:cliente_id>', methods=['GET'])
def cliente_listar_meus_pedidos(cliente_id):
    try:
        db = get_db()
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
            db.close()
            return jsonify([]), 200 # Retorna lista vazia se não houver pedidos

        for pedido_row in pedidos_db:
            pedido_dict = dict(pedido_row)
            cursor.execute("""
                SELECT p.nome as produto_nome, ip.quantidade, ip.preco_unitario_compra
                FROM itens_pedido ip
                JOIN produtos p ON ip.produto_id = p.id
                WHERE ip.pedido_id = ?
            """, (pedido_dict['id'],))
            itens = [dict(item_row) for item_row in cursor.fetchall()]
            pedido_dict['itens'] = itens
            pedidos.append(pedido_dict)
        db.close()
        return jsonify(pedidos), 200
    except Exception as e:
        return jsonify({"erro": f"Erro interno ao listar seus pedidos: {str(e)}"}), 500


# --- Inicialização ---
if __name__ == '__main__':
    init_db()
    app.run(debug=True)