from app.services.openapi_importer import templates_from_openapi


def test_templates_from_openapi_includes_all_supported_methods():
    spec = {
        "schemes": ["https"],
        "host": "example.com",
        "basePath": "/api",
        "paths": {
            "/users": {
                "get": {
                    "tags": ["Users"],
                    "summary": "Get user",
                    "operationId": "Users_Get",
                    "parameters": [{
                        "name": "userId",
                        "in": "query",
                        "required": True,
                        "type": "integer",
                    }],
                },
                "post": {
                    "tags": ["Users"],
                    "summary": "Create user",
                    "operationId": "Users_Create",
                    "parameters": [],
                },
                "put": {
                    "tags": ["Users"],
                    "summary": "Update user",
                    "operationId": "Users_Update",
                    "parameters": [],
                },
                "delete": {
                    "tags": ["Users"],
                    "summary": "Delete user",
                    "operationId": "Users_Delete",
                    "parameters": [],
                },
            },
        },
    }

    templates = templates_from_openapi(spec, "https://example.com/swagger.json")

    assert [template["restMethod"] for template in templates] == ["GET", "POST", "PUT", "DELETE"]
    assert templates[0]["endpoint"] == "https://example.com/api/users"
    assert '"userId": 0' in templates[0]["restParamsText"]


def test_templates_include_optional_path_parameters_and_bound_recursive_models():
    spec = {
        "host": "example.com",
        "definitions": {
            "Node": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "child": {"$ref": "#/definitions/Node"},
                },
            },
        },
        "paths": {
            "/users/{id}": {
                "post": {
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "type": "integer"},
                        {"name": "verbose", "in": "query", "required": False, "type": "boolean"},
                        {"name": "body", "in": "body", "required": True, "schema": {"$ref": "#/definitions/Node"}},
                    ],
                },
            },
        },
    }

    template = templates_from_openapi(spec, "https://example.com/swagger.json")[0]

    assert '"id": 0' in template["restParamsText"]
    assert '"verbose": false' in template["restParamsText"]
    assert len(template["restBodyText"]) < 200
    assert '"child": {}' in template["restBodyText"]
