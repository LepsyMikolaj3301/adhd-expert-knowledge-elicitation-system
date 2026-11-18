#!/usr/bin/env bash
# Rebuild SysON projects from text. A source is a folder with *.sysml files; its name
# becomes the project name. An existing project with that name is DELETED and recreated,
# so UI-only edits in it are lost.
# Usage: ./push.sh [source ...]   (default: every folder in src/)
#   source = a folder name under src/, or a path to any folder with *.sysml files
#            (e.g. ./push.sh ../model  ->  project "model")
set -euo pipefail
HOST="${SYSON_URL:-http://localhost:8080}"
HERE="$(cd "$(dirname "$0")" && pwd)"

dirs=()
if [ $# -eq 0 ]; then
  for d in "$HERE"/src/*/; do [ -d "$d" ] && dirs+=("${d%/}"); done
else
  for a in "$@"; do
    if   [ -d "$HERE/src/$a" ]; then dirs+=("$HERE/src/$a")
    elif [ -d "$a" ];           then dirs+=("$(cd "$a" && pwd)")
    else echo "nie ma takiego zrodla: $a" >&2; exit 1; fi
  done
fi
[ ${#dirs[@]} -gt 0 ] || { echo "brak zrodel: dodaj folder z plikami *.sysml do src/ albo podaj sciezke" >&2; exit 1; }

curl -sf "$HOST/api/rest/projects" >/dev/null || { echo "SysON nie odpowiada pod $HOST - uruchom: docker compose up -d" >&2; exit 1; }

gql() { curl -sf "$HOST/api/graphql" -H 'content-type: application/json' -d "$1"; }
uuid() { python3 -c 'import uuid;print(uuid.uuid4())'; }
jget() { python3 -c "import sys,json;d=json.load(sys.stdin);print($1)"; }

# print "id<TAB>name<TAB>view-def-name" for every view in the commit at REST base URL $1.
# Walks packages only, in parallel: downloading all elements (/elements) takes ~5 min for
# an 18k-element model, this takes seconds. A `view` nested in a non-package is not found.
find_views() { python3 - "$1" <<'PY'
import sys,json,urllib.request
from concurrent.futures import ThreadPoolExecutor
base=sys.argv[1]; pool=ThreadPoolExecutor(16)
get=lambda i: json.load(urllib.request.urlopen(f'{base}/elements/{i}'))
level=json.load(urllib.request.urlopen(base+'/roots')); views=[]
while level:
    ids=[m['@id'] for p in level for m in (p.get('ownedMember') or [])]
    kids=list(pool.map(get, ids))
    views+=[e for e in kids if e['@type']=='ViewUsage']
    level=[e for e in kids if e['@type'] in ('Package','LibraryPackage')]
defs={}
for v in views:
    d=(v.get('viewDefinition') or {}).get('@id')
    if d and d not in defs: defs[d]=get(d).get('name')
    print(v['@id'], v['name'], defs.get(d) or '-', sep='\t')
PY
}

for dir in "${dirs[@]}"; do
  name="$(basename "$dir")"
  # delete any existing project with this name
  gql '{"query":"{viewer{projects(first:100){edges{node{id name}}}}}"}' \
    | python3 -c "import sys,json
for e in json.load(sys.stdin)['data']['viewer']['projects']['edges']:
  if e['node']['name']=='$name': print(e['node']['id'])" \
    | while read -r pid; do
        gql "{\"query\":\"mutation(\$i:DeleteProjectInput!){deleteProject(input:\$i){__typename}}\",\"variables\":{\"i\":{\"id\":\"$(uuid)\",\"projectId\":\"$pid\"}}}" >/dev/null
      done

  out=$(gql "{\"query\":\"mutation(\$i:CreateProjectInput!){createProject(input:\$i){... on CreateProjectSuccessPayload{project{id currentEditingContext{id}}}}}\",\"variables\":{\"i\":{\"id\":\"$(uuid)\",\"name\":\"$name\",\"templateId\":\"blank-project\",\"libraryIds\":[]}}}")
  pid=$(echo "$out" | jget "d['data']['createProject']['project']['id']")
  ec=$(echo "$out" | jget "d['data']['createProject']['project']['currentEditingContext']['id']")

  # all files go up as ONE document: SysON resolves references only to what is already
  # loaded, so with one upload per file every reference to a later file (types,
  # specializations, `expose`) would silently be lost
  r=$(cat "$dir"/*.sysml | curl -sf "$HOST/api/graphql/upload" \
    -F operations="{\"query\":\"mutation(\$input:UploadDocumentInput!){uploadDocument(input:\$input){__typename ... on ErrorPayload{message}}}\",\"variables\":{\"input\":{\"id\":\"$(uuid)\",\"editingContextId\":\"$ec\",\"readOnly\":false},\"file\":null}}" \
    -F map='{"0":"variables.file"}' -F "0=@-;filename=$name.sysml")
  echo "$name ($(ls "$dir"/*.sysml | wc -l) plikow): $(echo "$r" | jget "d['data']['uploadDocument']['__typename']")"

  # view defs that `render asInterconnectionDiagram` (read from the text: the library
  # rendering is not in the REST element list)
  ic_defs=$(cat "$dir"/*.sysml | python3 -c "
import sys,re
print(' '.join(re.findall(r'view\s+def\s+(?:<\w+>\s+)?(\w+)\s*(?::>\s*[\w:]+\s*)?\{[^}]*?render\s+asInterconnectionDiagram', sys.stdin.read())))")

  # a text `view` is only a model element; create its diagram too: Interconnection View
  # when its view def renders asInterconnectionDiagram (or its name contains
  # "interconnection"), otherwise General View
  find_views "$HOST/api/rest/projects/$pid/commits/$pid" | while IFS=$'\t' read -r vid vname vdef; do
      label='General View'
      if [[ "${vname,,}" == *interconnection* || " $ic_defs " == *" $vdef "* ]]; then label='Interconnection View'; fi
      python3 - "$ec" "$vid" "$vname" "$label" "$HOST" <<'PY'
import sys,json,uuid,urllib.request
ec,vid,vname,label,host=sys.argv[1:]
def gql(q,v):
    r=urllib.request.Request(host+'/api/graphql',json.dumps({'query':q,'variables':v}).encode(),{'content-type':'application/json'})
    return json.load(urllib.request.urlopen(r))
d=gql('query($e:ID!,$o:ID!){viewer{editingContext(editingContextId:$e){representationDescriptions(objectId:$o){edges{node{id label}}}}}}',{'e':ec,'o':vid})
rid=[n['node']['id'] for n in d['data']['viewer']['editingContext']['representationDescriptions']['edges'] if n['node']['label']==label][0]
r=gql('mutation($i:CreateRepresentationInput!){createRepresentation(input:$i){__typename}}',{'i':{'id':str(uuid.uuid4()),'editingContextId':ec,'objectId':vid,'representationDescriptionId':rid,'representationName':vname}})
print(f'{vname}: {label} -> '+r['data']['createRepresentation']['__typename'])
PY
    done
done
