import more_itertools
import requests
import json
import sys

CODE_SEARCH_URL = "https://api.github.com/search/code"
ISSUES_SEARCH_URL = "https://api.github.com/search/issues"
REPO_SEARCH_URL = "https://api.github.com/search/repositories"

# TODO: set git credentials
# GITHUB_CREDENTIALS = ("git_username", "token")


class GitHubIssueObj:
    def __init__(self, issue_url, html_issue_url, repo_url, nr_stars, nr_open_issues):
        self.issue_url = issue_url
        self.html_issue_url = html_issue_url
        self.repo_url = repo_url
        self.nr_stars = nr_stars
        self.nr_open_issues = nr_open_issues

    def get_issue_url(self):
        return self.issue_url

    def get_html_issue_url(self):
        return self.html_issue_url

    def get_nr_stars(self):
        return self.nr_stars

    def get_repo_url(self):
        return self.repo_url

    def get_nr_open_issue(self):
        return self.nr_open_issues

    def get_dict_repr(self):
        return {
            "html_issue_url": self.html_issue_url,
            "raw_issue_url": self.issue_url,
            "repo_url": self.repo_url,
            "start_count": self.nr_stars,
            "open_issues_count": self.nr_open_issues

        }

    def __str__(self):
        return json.dumps(self.get_dict_repr())


def are_keywords_in_code(code_search_keywords_lst, repo):
    for code_search_keyword in code_search_keywords_lst:
        params = {
            'q': "{keywords_str} in:file repo:{repo}".format(
                keywords_str=code_search_keyword,
                repo=repo),
            "per_page": "100"
        }

        # get search results
        response = requests.get(CODE_SEARCH_URL, params=params, auth=GITHUB_CREDENTIALS)
        total_count = response.json().get("total_count", 0)

        if total_count != 0:
            return True

    return False


def get_issues(config_data: dict) -> list:
    github_repo_obj_lst = []
    processed_html_issues_url_set = set()
    for chunk in list(more_itertools.chunked(config_data.get("search_keywords"), 2)):
        stop = False

        issue_keywords_str = "("
        issue_keywords_str += " OR ".join(chunk)
        issue_keywords_str += ")"
        issue_keywords_str += " AND (reproducible OR reproduce)"

        # check params again, especially for '(' and ')'
        params = {
            'q': "{issue_keywords_str} is:issue is:{issue_status} {languages_str} created:>={min_creation_date}".format(
                issue_keywords_str=issue_keywords_str,
                issue_status=config_data.get("issue_status", "open"),
                languages_str=config_data.get("languages_str"),
                min_creation_date=config_data.get("min_creation_date")),
            "per_page": "100"
        }

        # get issues
        print(f"Performing query: {params}")
        response = requests.get(ISSUES_SEARCH_URL, params=params, auth=GITHUB_CREDENTIALS)
        response.raise_for_status()

        while True:
            for issue in response.json().get('items', []):
                # print(f"Processing: {json.dumps(issue, indent=2)}")
                try:
                    html_issue_url = issue["html_url"]
                    if html_issue_url in processed_html_issues_url_set:
                        print(f"{html_issue_url} DISCARDED -> already processed")
                        continue
                    processed_html_issues_url_set.add(html_issue_url)

                    # check if this issue has to be skipped
                    if html_issue_url in config_data.get("excluded_issues_url_lst", []):
                        print(f"{html_issue_url} DISCARDED -> present in exclusion list")
                        continue

                    # check labels
                    issue_labels = issue["labels"]
                    labels_to_match_lst = config_data.get("issue_labels", [])
                    if len(issue_labels) > 0 and len(labels_to_match_lst) > 0 \
                            and not any(
                        any(
                            label_to_match.lower() in label["name"].lower()
                            for label_to_match in labels_to_match_lst
                        )
                        for label in issue_labels
                    ):
                        print(f"{html_issue_url} DISCARDED -> contains irrelevant labels")
                        continue

                    # get issue's title and body
                    issue_content = issue["title"]
                    if issue["body"]:
                        issue_content += " " + issue["body"]

                    # get issue's comments
                    comments_url = issue["comments_url"]
                    comments_obj_lst = requests.get(comments_url, auth=GITHUB_CREDENTIALS).json()
                    for comment_obj in comments_obj_lst:
                        if comment_obj["body"]:
                            issue_content += " " + comment_obj["body"]

                    # search for keywords for exclusion in the issue's content
                    keywords_exclusion_lst = config_data.get("keywords_exclusion_lst", [])
                    if len(keywords_exclusion_lst) > 0 and any(
                            keyword.lower() in issue_content.lower() for keyword in keywords_exclusion_lst):
                        print(
                            f"{html_issue_url} DISCARDED -> issue content contains keyword from keywords_exclusion_lst")
                        continue

                    # get issue's source repo
                    repo_url = issue["repository_url"]
                    src_repo_obj = requests.get(repo_url, auth=GITHUB_CREDENTIALS).json()
                    repo_updated_at = src_repo_obj.get("updated_at", None)
                    if repo_updated_at:
                        repo_updated_at = repo_updated_at.split("T")[0]
                        if repo_updated_at < config_data.get("min_repo_update_date", ""):
                            print(f"{html_issue_url} DISCARDED -> too old, updated: {repo_updated_at}")
                            continue

                    # min nr of stars
                    repo_stars_count = src_repo_obj["stargazers_count"]
                    if repo_stars_count < config_data.get("min_nr_stars", 0):
                        print(f"{html_issue_url} DISCARDED -> small stars count: {repo_stars_count}")
                        continue

                    # search for keywords in the repo's code
                    code_search_keywords_lst = config_data.get("code_search_keywords_lst", [])
                    if len(code_search_keywords_lst) > 0 and not are_keywords_in_code(code_search_keywords_lst,
                                                                                      src_repo_obj["full_name"]):
                        print(f"{html_issue_url} DISCARDED -> required keywords not found in the repo code")
                        continue

                    # create object
                    github_repo_obj = GitHubIssueObj(
                        issue["url"],
                        html_issue_url,
                        repo_url,
                        src_repo_obj["stargazers_count"],
                        src_repo_obj["open_issues_count"]
                    )
                    github_repo_obj_lst.append(github_repo_obj)

                    if len(github_repo_obj_lst) == config_data.get("get_total_count"):
                        print(f"STOP -> reached total count")
                        stop = True
                        break

                finally:
                    pass
                    # print(issue)
            # go to next page with issues if exists
            if stop or not response.links.get('next') or 'url' in response.links.get('next'):
                break

            response = requests.get(response.links.get('next')["url"])

    if len(github_repo_obj_lst) > 0:
        github_repo_obj_lst.sort(key=lambda x: x.get_nr_stars(), reverse=True)

    return github_repo_obj_lst[:config_data.get("get_top_count")]


# Press the green button in the gutter to run the script.
if __name__ == '__main__':

    if len(sys.argv) < 2:
        exit("Missing arguments.\nUsage: python main.py [output_file_name]")

    config_data = {
        "get_top_count": 50,
        "get_total_count": 50,
        "min_nr_stars": 1000,
        "min_creation_date": "2017-01-01",
        "min_repo_update_date": "2022-09-01",
        "languages_str": "language:c language:c++",
        "issue_status": "closed",
        "issue_labels": [
            "bug",
            "race",
            "race-condition",
            "concurrency",
            "deadlock",
            "dead-lock",
        ],
        "search_keywords": [
            "race",
            "dead-lock",
            "deadlock",
            "concurrent",
            "concurrency",
            "atomic",
            "synchronize",
            "synchronous",
            "synchronization",
            "starvation",
            "suspension",
            "livelock",
            "live-lock",
            "multi-threaded",
            "multithreading",
            "multi-thread",
            "thread",
            "blocked",
            "locked",
        ],
        "keywords_exclusion_lst": [
            "game",
            "games",
            "windows",
            "gpu",
            "cuda",
            "display"
        ],
        "code_search_keywords_lst": [
            "pthread",
            "openmp"
        ],
        "excluded_issues_url_lst": [
            "https://github.com/apple/cups/issues/6089",
            "https://github.com/microsoft/terminal/issues/14863",
            "https://github.com/opencv/opencv/issues/23228"
        ]
    }

    github_repo_obj_lst = get_issues(config_data)
    print(f"Founded repo: {len(github_repo_obj_lst)}")
    with open(sys.argv[1], "w") as f:
        json.dump([x.get_dict_repr() for x in github_repo_obj_lst], f, indent=2)
