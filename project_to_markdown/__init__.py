import os
import re
from argparse import ArgumentParser, FileType
from collections import defaultdict
from urllib.parse import urlparse, urlunparse
import requests
from github import Github, Project


try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass


def get_milestone_html_url(milestone):
    milestone_api_url = milestone.url

    milestone_api_path = urlparse(milestone_api_url).path

    matches = re.match(r'/repos/([^/]+)/([^/]+)/milestones/(\d+)', milestone_api_path)

    org, repo, number = matches.groups()

    milestone_path = f"{org}/{repo}/milestone/{number}"

    return urlunparse(('https', 'github.com', milestone_path, '', '', ''))


def get_card_content(card):
    # We can't use lru_cache here because `card` is not hashable.
    # Unfortunately.
    # In place of that we're just using a memoization off of the
    # function called.  It's hacky but.. well, better than nothing, right?

    if not hasattr(get_card_content, '_card_content_memo'):
        setattr(get_card_content, '_card_content_memo', {})
    memo = getattr(get_card_content, '_card_content_memo')

    if card.id not in memo:
        try:
            memo[card.id] = card.get_content()
        except:
            memo[card.id] = None

    return memo.get(card.id, None)


def format_card(card):
    content = get_card_content(card)

    if content:
        line = f"{content.title} - [Issue #{content.number}]({content.html_url})"

        if content.state == "closed":
            line = f"~~{line}~~"
    else:
        line = card.note

    line = f"{line}".strip()

    # We've wrapped stuff in CDATA to prevent it from messing up the github pages.
    # If there's anything that's CDATA let's pull it outta there.
    line = re.sub(r'<!\[CDATA\[(.*?)\]\]>', '\g<1>', line, flags=re.MULTILINE | re.DOTALL)

    if not line:
        return None

    # If multiple lines let's space them out so they're properly handled as
    # part of the list item
    line = line.replace("\n", "\n  ")

    return f"* {line}"


def format_cards(cards):
    return list(filter(None, [format_card(card) for card in cards]))


def convert_to_markdown(json_data):
    # Dictionary to hold the categorized items
    categorized_items = {}

    # Iterate over the items and categorize them by status
    for item in json_data["data"]["node"]["items"]["nodes"]:
        # Each item's status and title are within fieldValues
        status = None
        title = None
        for field in item["fieldValues"]["nodes"]:
            if field.get("field", {}).get("name") == "Status":
                status = field.get("name")
            elif field.get("field", {}).get("name") == "Title":
                title = field.get("text")
        
        # If status is found, add the item to the category
        if status and title:
            if status not in categorized_items:
                categorized_items[status] = []
            categorized_items[status].append(title)

    # Now convert the categorized items to markdown format
    markdown_output = "# Project Board Status\n\n"
    for status, titles in categorized_items.items():
        markdown_output += f"## {status}\n"
        for title in titles:
            markdown_output += f"- [ ] {title}\n"  # Using task list format
        markdown_output += "\n"  # Add a newline for formatting

    return markdown_output


def graphql_query(query, headers):
    """
    Helper function to perform a GraphQL query using the requests library.
    """
    request = requests.post('https://api.github.com/graphql', json={'query': query}, headers=headers)
    if request.status_code == 200:
        return request.json()
    else:
        raise Exception("Query failed to run by returning code of {}. {}".format(request.status_code, query))

def get_login_and_project_number_from_uri(uri):
    # Extract the org, repo, and project number from the URI
    project_path = urlparse(uri).path
    matches = re.match(r'^/orgs/([^/]+)/projects/(\d+)$', project_path) or re.match(r'^/([^/]+/[^/]+)/projects/(\d+)$', project_path)
    if not matches:
        raise ValueError(f"Invalid project URI: {uri}")

    variables = {
        "login": matches.group(1),
        "projectNumber": int(matches.group(2))
    }
    return variables["login"], variables["projectNumber"]

def get_project_node_id_from_uri(token, uri):
    headers = {"Authorization": f"bearer {token}"}

    query = """
    query{
        organization(login: "%s"){
            projectV2(number: %i) {
                id
            }
        }
    }
    """ % get_login_and_project_number_from_uri(uri)

    # Perform the query
    project_id_response = graphql_query(query, headers)
    # print(f"project_id_response: {project_id_response}")
    node_id = project_id_response['data']['organization']['projectV2']['id']
    print(f"project node_id: {node_id}")
    return node_id

def get_project_contents(token, uri):
    node_id = get_project_node_id_from_uri(token, uri)
    # Your personal access token
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # The GraphQL query. Be sure to replace PROJECT_ID with your actual Project ID
    query = """
    query {
    node(id: "%s") {
        ... on ProjectV2 {
        items(first: 20) {
            nodes {
            id
            fieldValues(first: 8) {
                nodes {
                ... on ProjectV2ItemFieldTextValue {
                    text
                    field {
                    ... on ProjectV2FieldCommon {
                        name
                    }
                    }
                }
                ... on ProjectV2ItemFieldDateValue {
                    date
                    field {
                    ... on ProjectV2FieldCommon {
                        name
                    }
                    }
                }
                ... on ProjectV2ItemFieldSingleSelectValue {
                    name
                    field {
                    ... on ProjectV2FieldCommon {
                        name
                    }
                    }
                }
                }
            }
            content {
                ... on DraftIssue {
                title
                body
                }
                ... on Issue {
                title
                assignees(first: 10) {
                    nodes {
                    login
                    }
                }
                }
                ... on PullRequest {
                title
                assignees(first: 10) {
                    nodes {
                    login
                    }
                }
                }
            }
            }
        }
        }
    }
    }
    """ % node_id

    # Perform the query
    project_id_response = graphql_query(query, headers)


    # For now, this will just print the raw response
    # print(project_id_response)
    return project_id_response


def get_issues_from_repo(token, org, repo):
    headers = {"Authorization": f"token {token}"}
    url = f"https://api.github.com/repos/{org}/{repo}/issues"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception("Failed to retrieve issues: {}".format(response.status_code))


def add_issues_to_project(token, project_uri, issues):
    headers = {"Authorization": f"Bearer {token}"}
    
    project = get_project_contents(token, project_uri)
    project_node_id = get_project_node_id_from_uri(token, project_uri)

    for issue in issues:
        # Construct the mutation query to add an issue to the project
        add_item_mutation = """
        mutation($projectId: ID!, $contentId: ID!) {
            addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
                item {
                    id
                }
            }
        }
        """
        variables = {
            "projectId": project_node_id,
            "contentId": issue['node_id']
        }

        # Perform the GraphQL mutation
        add_response = requests.post('https://api.github.com/graphql',
                                     json={'query': add_item_mutation, 'variables': variables},
                                     headers=headers)
        if add_response.status_code != 200:
            raise Exception(f"Failed to add issue {issue['title']} to project: {add_response.status_code}")

        # Update the status of the issue to 'Extracted'
        update_status_mutation = """
        mutation($itemId: ID!, $fieldId: ID!, $value: String!) {
            updateProjectV2ItemField(input: {itemId: $itemId, fieldId: $fieldId, value: $value}) {
                item {
                    id
                }
            }
        }
        """
        # You need to replace 'FIELD_ID' with the actual ID of the 'Status' field in your project
        status_field_id = "Status"
        status_value = "Extracted"
        item_id = add_response.json()['data']['addProjectV2ItemById']['item']['id']

        variables = {
            "itemId": item_id,
            "fieldId": status_field_id,
            "value": status_value
        }

        update_response = requests.post('https://api.github.com/graphql',
                                        json={'query': update_status_mutation, 'variables': variables},
                                        headers=headers)
        if update_response.status_code != 200:
            raise Exception(f"Failed to set status of issue {issue['title']} to 'Extracted': {update_response.status_code}")




def get_field_id(token, project_uri):
    headers = {"Authorization": f"Bearer {token}"}

    project_node_id = get_project_node_id_from_uri(token, project_uri)

    # GraphQL query to fetch project fields
    query = """
    query($projectId: ID!) {
        node(id: $projectId) {
            ... on ProjectV2 {
                fields(first: 10) {
                    nodes {
                        id
                        name
                        # Add here any general fields that are common to all field types
                    }
                }
            }
        }
    }
    """


    variables = {"projectId": project_node_id}

    response = requests.post('https://api.github.com/graphql',
                             json={'query': query, 'variables': variables},
                             headers=headers)

    if response.status_code == 200:
        print(response.json())
        # fields = response.json()['data']['node']['fields']['nodes']
        # for field in fields:
        #     print(f"Field Name: {field['name']}, Field ID: {field['id']}")
    else:
        raise Exception(f"Failed to fetch project fields: {response.status_code}")



def cli():
    parser = ArgumentParser()

    parser.add_argument('--github-token', type=str, default=os.environ.get('GITHUB_TOKEN'))
    parser.add_argument('--output-file', type=FileType('w'))
    parser.add_argument('project_uri')
    parser.add_argument('--org', type=str, help='GitHub organization name')
    parser.add_argument('--repo', type=str, help='GitHub repository name')
    parser.add_argument('--get-field-id', action='store_true', help='Get field IDs for a project')

    args = parser.parse_args()

    token = args.github_token
    output_file = args.output_file
    project_uri = args.project_uri
    if args.org and args.repo:
        issues = get_issues_from_repo(token, args.org, args.repo)
        print(f"issues: {issues}")
        add_issues_to_project(token, project_uri, issues)

    if args.get_field_id:
        get_field_id(args.github_token, args.project_uri)

    project = get_project_contents(token, project_uri)

    markdown = convert_to_markdown(project)

    if output_file:
        output_file.write(markdown)
    else:
        print(markdown)


if __name__ == "__main__":
    cli()
