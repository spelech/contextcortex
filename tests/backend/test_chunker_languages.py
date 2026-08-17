import pytest
from unittest.mock import patch, MagicMock
from app.services.chunker import (
    extract_symbols_and_chunks, get_file_outline, detect_language, is_code_file,
    chunk_markdown, split_by_length, get_tree_sitter_parser, _PARSERS
)

def test_language_detection():
    assert detect_language("app/main.go") == "go"
    assert detect_language("src/lib.rs") == "rust"
    assert detect_language("src/App.tsx") == "tsx"
    assert detect_language("src/index.ts") == "typescript"
    assert detect_language("src/Server.java") == "java"
    assert detect_language("main.cpp") == "cpp"
    assert detect_language("main.c") == "c"
    assert detect_language("Program.cs") == "c_sharp"
    assert detect_language("script.rb") == "ruby"
    assert detect_language("index.php") == "php"
    assert detect_language("unknown.xyz") == "text"

    assert is_code_file("app.py") is True
    assert is_code_file("notes.md") is False
    assert is_code_file("config.json") is False

def test_get_tree_sitter_parser_caching_and_fallbacks():
    # Cached parser
    p_py = get_tree_sitter_parser("python")
    assert p_py is not None
    assert get_tree_sitter_parser("python") is p_py

    # Fallback for c_sharp / csharp
    with patch("tree_sitter_language_pack.get_parser") as mock_get_parser:
        # First call fails, second call succeeds with alt_name
        mock_parser = MagicMock()
        mock_get_parser.side_effect = [Exception("Language not found: c_sharp"), mock_parser]
        
        # Clear cache for key
        if "c_sharp_test" in _PARSERS:
            del _PARSERS["c_sharp_test"]
            
        parser = get_tree_sitter_parser("c_sharp_test")
        assert parser is mock_parser

    # Exception importing/getting parser returns None
    with patch("tree_sitter_language_pack.get_parser", side_effect=Exception("Fatal parser crash")):
        if "failing_lang" in _PARSERS:
            del _PARSERS["failing_lang"]
        res = get_tree_sitter_parser("failing_lang")
        assert res is None

def test_extract_symbols_unsupported_language():
    code = "echo 'Hello world'\necho 'Line 2'\n"
    # Plain text file or language where parser returns None
    with patch("app.services.chunker.get_tree_sitter_parser", return_value=None):
        result = extract_symbols_and_chunks(code, "script.custom", repo="custom-repo")
        assert len(result.chunks) >= 1
        assert result.symbols == []
        assert result.outline == []

def test_extract_symbols_parser_parse_exception():
    code = "def broken(): pass"
    mock_parser = MagicMock()
    mock_parser.parse.side_effect = Exception("AST parser segfault")
    
    with patch("app.services.chunker.get_tree_sitter_parser", return_value=mock_parser):
        result = extract_symbols_and_chunks(code, "test.py", repo="error-repo")
        assert len(result.chunks) >= 1
        assert result.symbols == []
        assert result.outline == []

def test_go_ast_extraction():
    code = """package main

import "fmt"

type Server struct {
    port int
}

func (s *Server) Start() error {
    fmt.Println("Starting")
    return nil
}

func main() {
    s := &Server{port: 8080}
    s.Start()
}
"""
    result = extract_symbols_and_chunks(code, "main.go", repo="go-app")
    symbols = [s.name for s in result.symbols]
    assert "Server" in symbols or "Start" in symbols or "main" in symbols
    assert len(result.chunks) >= 1

def test_rust_ast_extraction():
    code = """pub struct User {
    pub id: u64,
    pub name: String,
}

impl User {
    pub fn new(id: u64, name: String) -> Self {
        Self { id, name }
    }
}

pub trait Authenticatable {
    fn authenticate(&self) -> bool;
}
"""
    result = extract_symbols_and_chunks(code, "src/user.rs", repo="rust-app")
    symbols = [s.name for s in result.symbols]
    assert "User" in symbols or "new" in symbols or "Authenticatable" in symbols

def test_typescript_and_tsx_ast_extraction():
    ts_code = """export interface UserConfig {
    timeout: number;
}

export class ApiClient {
    private config: UserConfig;
    constructor(config: UserConfig) {
        this.config = config;
    }
    async fetchData(): Promise<string> {
        return "data";
    }
}
"""
    result = extract_symbols_and_chunks(ts_code, "src/api.ts", repo="web-app")
    symbols = [s.name for s in result.symbols]
    assert "UserConfig" in symbols or "ApiClient" in symbols or "fetchData" in symbols

    tsx_code = """export function ProfileHeader({ name }: { name: string }) {
    return <h1>Hello, {name}</h1>;
}
"""
    tsx_result = extract_symbols_and_chunks(tsx_code, "src/Header.tsx", repo="web-app")
    assert len(tsx_result.chunks) >= 1

def test_java_ast_extraction():
    java_code = """public class OrderService {
    private int orderId;
    public void processOrder(int id) {
        this.orderId = id;
    }
}
"""
    result = extract_symbols_and_chunks(java_code, "OrderService.java")
    symbols = [s.name for s in result.symbols]
    assert "OrderService" in symbols or "processOrder" in symbols

def test_csharp_ast_extraction():
    cs_code = """namespace MyApp.Services
{
    public interface IUserService
    {
        Task<User> GetUserAsync(int id);
    }

    public class UserService : IUserService
    {
        public async Task<User> GetUserAsync(int id)
        {
            return await _context.Users.FindAsync(id);
        }
    }
}
"""
    result = extract_symbols_and_chunks(cs_code, "Services/UserService.cs", repo="dotnet-core")
    symbols = [s.name for s in result.symbols]
    assert "IUserService" in symbols
    assert "UserService" in symbols
    assert "GetUserAsync" in symbols
    assert any(s.full_symbol == "UserService.GetUserAsync" for s in result.symbols)
    assert len(result.chunks) >= 2

def test_cpp_and_c_ast_extraction():
    cpp_code = """class Engine {
public:
    void start() {}
};

int main() {
    Engine e;
    e.start();
    return 0;
}
"""
    result = extract_symbols_and_chunks(cpp_code, "engine.cpp")
    symbols = [s.name for s in result.symbols]
    assert "Engine" in symbols or "start" in symbols or "main" in symbols

def test_ruby_and_php_ast_extraction():
    ruby_code = """class UserHelper
  def format_name(name)
    name.capitalize
  end
end
"""
    rb_result = extract_symbols_and_chunks(ruby_code, "helper.rb", repo="rails-app")
    rb_symbols = [s.name for s in rb_result.symbols]
    assert "UserHelper" in rb_symbols or "format_name" in rb_symbols

    php_code = """<?php
class ProductController {
    public function listProducts() {
        return [];
    }
}
"""
    php_result = extract_symbols_and_chunks(php_code, "ProductController.php", repo="php-app")
    php_symbols = [s.name for s in php_result.symbols]
    assert "ProductController" in php_symbols or "listProducts" in php_symbols

def test_large_function_subchunking():
    large_func = "def very_long_function():\n" + "\n".join([f"    x_{i} = {i} * 2" for i in range(100)]) + "\n    return x_99\n"
    result = extract_symbols_and_chunks(large_func, "large.py", max_chunk_chars=300)
    assert len(result.chunks) > 1
    assert result.chunks[0].symbol is not None

def test_code_without_ast_symbols():
    script_code = "# simple script without functions or classes\na = 1\nb = 2\nc = a + b\nprint(c)\n"
    result = extract_symbols_and_chunks(script_code, "script.py")
    assert len(result.chunks) == 1
    assert result.chunks[0].symbol is None
    assert result.chunks[0].kind == "module"

def test_get_file_outline_helper():
    code = "class A:\n    def b(self):\n        pass\n"
    outline = get_file_outline(code, "test.py")
    assert len(outline) >= 1
    assert any("A" in item or "b" in item for item in outline)

def test_markdown_chunking_with_subchunks():
    md = "# Long Heading\n\n" + "\n\n".join([f"Paragraph {i}: " + ("lorem ipsum " * 20) for i in range(20)])
    chunks = chunk_markdown(md, max_chars=400)
    assert len(chunks) > 1
    assert all(c.heading == "Long Heading" for c in chunks)

def test_markdown_chunking_with_nested_headings_and_empty():
    md = """# Top Title
Introduction text.

## Section 1
Content 1

### Subsection 1.1
Content 1.1

## Section 2
Content 2
"""
    chunks = chunk_markdown(md, max_chars=500)
    assert len(chunks) == 4
    headings = [c.heading for c in chunks]
    assert "Top Title" in headings
    assert "Section 1" in headings
    assert "Subsection 1.1" in headings
    assert "Section 2" in headings
