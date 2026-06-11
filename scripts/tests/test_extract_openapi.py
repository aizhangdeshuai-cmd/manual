import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "extract-openapi.py"


class ExtractOpenAPITests(unittest.TestCase):
    def test_yaml_spec(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "openapi.yaml"
            f.write_text("""\
openapi: 3.0.0
info:
  title: Test API
  version: 1.0.0
paths:
  /users:
    get:
      operationId: listUsers
      summary: List all users
      tags: [users]
      parameters:
        - name: page
          in: query
          required: false
          schema: {type: integer}
      responses:
        '200': {description: OK}
    post:
      operationId: createUser
      summary: Create a user
      tags: [users]
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/User'
      responses:
        '201': {description: Created}
  /users/{id}:
    get:
      operationId: getUser
      summary: Get a user
      tags: [users]
      parameters:
        - name: id
          in: path
          required: true
          schema: {type: string}
      responses:
        '200': {description: OK}
components:
  schemas:
    User:
      type: object
      required: [id, name]
      properties:
        id: {type: string, description: 'User ID'}
        name: {type: string, description: 'User name'}
        email: {type: string, format: email}
        role: {type: string, enum: [admin, user, guest]}
""", encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
            if r.returncode != 0 and "PyYAML" in r.stderr:
                self.skipTest("PyYAML not installed; skipping YAML test")
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            parts = r.stdout.split("---SCHEMAS---", 1)
            self.assertEqual(len(parts), 2)
            endpoints = json.loads(parts[0])
            schemas = json.loads(parts[1])
            self.assertEqual(len(endpoints), 3)
            self.assertEqual(endpoints[0]["path"], "/users")
            self.assertEqual(endpoints[0]["method"], "GET")
            self.assertEqual(endpoints[1]["method"], "POST")
            self.assertEqual(endpoints[1]["request_body_ref"], "#/components/schemas/User")
            self.assertEqual(len(schemas), 1)
            self.assertEqual(schemas[0]["name"], "User")
            self.assertEqual(schemas[0]["field_count"], 4)
            required = {f["name"] for f in schemas[0]["fields"] if f["required"]}
            self.assertIn("id", required)
            self.assertIn("name", required)

    def test_json_spec(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "openapi.json"
            f.write_text(json.dumps({
                "openapi": "3.0.0",
                "info": {"title": "T", "version": "1"},
                "paths": {
                    "/items": {
                        "get": {
                            "operationId": "listItems",
                            "tags": ["items"],
                            "responses": {"200": {"description": "OK"}}
                        }
                    }
                }
            }), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            parts = r.stdout.split("---SCHEMAS---", 1)
            endpoints = json.loads(parts[0])
            self.assertEqual(len(endpoints), 1)
            self.assertEqual(endpoints[0]["path"], "/items")


if __name__ == "__main__":
    unittest.main()
