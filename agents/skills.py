"""Skills taxonomy shared by CV parsing and job analysis.

One canonical name per skill, with aliases and a category. Matching is word-boundary,
case-insensitive. Deterministic on purpose: the same text always yields the same skills.
"""

import re
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Skill:
    name: str
    category: str
    aliases: tuple[str, ...] = ()
    # Ambiguous short aliases (e.g. "Go") must appear in a tech context to count.
    needs_context: bool = False


_S = Skill
TAXONOMY: tuple[Skill, ...] = (
    # Cloud platforms
    _S("AWS", "cloud", ("amazon web services", "aws cloud")),
    _S("Microsoft Azure", "cloud", ("azure",)),
    _S("Google Cloud", "cloud", ("gcp", "google cloud platform")),
    _S("OpenStack", "cloud"),
    # AWS services
    _S("Amazon EC2", "aws", ("ec2",)),
    _S("Amazon RDS", "aws", ("rds", "aurora")),
    _S("AWS DMS", "migration", ("database migration service", "dms")),
    _S("AWS Lambda", "aws", ("lambda functions", "aws lambda")),
    _S("Amazon EKS", "containers", ("eks",)),
    _S("Amazon S3", "aws", ("s3",)),
    _S("AWS Landing Zone", "aws", ("control tower", "landing zone", "landing zones")),
    _S("AWS Organizations", "aws"),
    # Azure services
    _S("Azure Kubernetes Service", "containers", ("aks",)),
    _S("Azure Active Directory", "security", ("entra id", "azure ad", "microsoft entra")),
    _S("Azure Functions", "azure"),
    # IaC
    _S("Terraform", "iac", ("hcl", "terraform cloud")),
    _S("Terragrunt", "iac"),
    _S("CloudFormation", "iac", ("aws cloudformation", "cfn")),
    _S("AWS CDK", "iac", ("cdk",)),
    _S("Pulumi", "iac"),
    _S("Bicep", "iac", ("arm templates", "azure resource manager")),
    _S("Ansible", "config_mgmt"),
    _S("Puppet", "config_mgmt"),
    _S("Chef", "config_mgmt", needs_context=True),
    _S("Packer", "iac"),
    # Containers
    _S("Docker", "containers", ("containers", "containerization", "containerisation")),
    _S("Kubernetes", "containers", ("k8s", "kubernetes clusters")),
    _S("Helm", "containers", ("helm charts",)),
    _S("Rancher", "containers"),
    _S("OpenShift", "containers"),
    _S("Istio", "containers", ("service mesh",)),
    _S("ArgoCD", "ci_cd", ("argo cd", "argo")),
    _S("Flux", "ci_cd", ("fluxcd",), needs_context=True),
    _S("GitOps", "ci_cd"),
    # CI/CD
    _S("Jenkins", "ci_cd"),
    _S("GitLab CI/CD", "ci_cd", ("gitlab ci", "gitlab-ci", "gitlab")),
    _S("GitHub Actions", "ci_cd"),
    _S("Azure DevOps", "ci_cd", ("azure pipelines",)),
    _S(
        "CI/CD",
        "ci_cd",
        (
            "continuous integration",
            "continuous delivery",
            "continuous deployment",
            "ci/cd pipelines",
            "cicd",
        ),
    ),
    # Languages
    _S("Java", "backend"),
    _S("Spring Boot", "backend", ("spring framework", "spring cloud")),
    _S("Python", "backend"),
    _S("Go", "backend", ("golang",), needs_context=True),
    _S("TypeScript", "backend"),
    _S("Node.js", "backend", ("nodejs",)),
    _S("C#", "backend", (".net", "dotnet")),
    _S("Bash", "backend", ("shell scripting",)),
    _S("PowerShell", "backend"),
    # Data
    _S("SQL Server", "database", ("mssql", "microsoft sql server")),
    _S("PostgreSQL", "database", ("postgres",)),
    _S("MySQL", "database", ("mariadb",)),
    _S("Oracle", "database", ("oracle db", "oracle database")),
    _S("MongoDB", "database", ("mongo",)),
    _S("Redis", "database"),
    _S("Kafka", "data", ("apache kafka", "msk")),
    _S("Snowflake", "data"),
    _S("Databricks", "data"),
    _S("Change Data Capture", "migration", ("cdc",)),
    # Architecture & practices
    _S("Microservices", "architecture", ("microservice", "micro-services")),
    _S(
        "Cloud Architecture",
        "architecture",
        ("solution architecture", "solutions architecture", "cloud architectures", "architecting"),
    ),
    _S(
        "Cloud Migration",
        "migration",
        ("migrations to the cloud", "cloud migrations", "lift and shift", "rehost", "replatform"),
    ),
    _S(
        "Infrastructure Modernization",
        "migration",
        ("modernization", "modernisation", "application modernization"),
    ),
    _S("Well-Architected Framework", "architecture", ("well-architected",)),
    _S("High Availability", "architecture", ("disaster recovery", "resilience", "fault tolerance")),
    _S("Scalability", "architecture", ("scalable", "scaling")),
    _S("Serverless", "architecture"),
    _S("Event-Driven Architecture", "architecture", ("event driven", "event-driven")),
    _S("API Design", "architecture", ("rest api", "rest apis", "api gateway", "openapi")),
    _S(
        "Networking",
        "networking",
        (
            "vpc",
            "vnet",
            "tcp/ip",
            "dns",
            "load balancing",
            "transit gateway",
            "hybrid connectivity",
        ),
    ),
    _S(
        "Cloud Security",
        "security",
        ("security architecture", "iam", "zero trust", "devsecops", "secure by design"),
    ),
    _S("Compliance", "security", ("iso 27001", "soc 2", "gdpr", "pci dss", "nis2", "dora")),
    _S("FinOps", "cost", ("cost optimization", "cost optimisation", "cloud cost")),
    _S(
        "Observability",
        "operations",
        ("monitoring", "prometheus", "grafana", "datadog", "cloudwatch", "opentelemetry", "elk"),
    ),
    _S("SRE", "operations", ("site reliability", "sre")),
    _S("Linux", "operations"),
    _S("Platform Engineering", "architecture", ("internal developer platform", "platform team")),
    _S("DevOps", "practices"),
    _S("Agile", "practices", ("scrum", "kanban")),
    _S(
        "Stakeholder Management",
        "leadership",
        ("stakeholder", "stakeholders", "client-facing", "customer-facing"),
    ),
    _S(
        "People Management",
        "leadership",
        (
            "line management",
            "people leadership",
            "managing a team",
            "team management",
            "lead a team",
            "leading teams",
        ),
    ),
    _S("Pre-Sales", "leadership", ("presales", "pre-sales", "technical sales")),
    _S(
        "Delivery Management",
        "leadership",
        ("delivery manager", "programme delivery", "project delivery"),
    ),
    _S("Machine Learning", "data", ("ml", "mlops"), needs_context=True),
    _S("Generative AI", "data", ("genai", "llm", "llms", "large language models")),
)

_CONTEXT = re.compile(
    r"\b(programming|language|languages|developer|engineering|code|coding|stack|"
    r"experience with|proficient|framework|tools?|using|with)\b",
    re.I,
)


@lru_cache
def _patterns() -> list[tuple[Skill, re.Pattern[str]]]:
    out = []
    for skill in TAXONOMY:
        terms = sorted({skill.name.lower(), *skill.aliases}, key=len, reverse=True)
        alt = "|".join(re.escape(t) for t in terms)
        # Word-ish boundaries that also work for terms like "c#", ".net", "ci/cd".
        out.append((skill, re.compile(rf"(?<![\w]){'(?:' + alt + ')'}(?![\w])", re.I)))
    return out


def by_name() -> dict[str, Skill]:
    return {s.name.lower(): s for s in TAXONOMY}


def canonical(name: str) -> str:
    """Map any alias ('k8s', 'Azure') to its canonical skill name; unknown names unchanged."""
    lowered = name.strip().lower()
    for skill in TAXONOMY:
        if lowered == skill.name.lower() or lowered in skill.aliases:
            return skill.name
    return name.strip()


def extract_skills(text: str) -> dict[str, int]:
    """Canonical skill name -> number of mentions."""
    found: dict[str, int] = {}
    if not text:
        return found
    for skill, pattern in _patterns():
        matches = list(pattern.finditer(text))
        if not matches:
            continue
        if skill.needs_context:
            matches = [m for m in matches if _is_tech_usage(text, m)]
            if not matches:
                continue
        found[skill.name] = len(matches)
    return found


def _is_tech_usage(text: str, m: re.Match[str]) -> bool:
    """For ambiguous terms ('Go', 'Chef', 'ML'): a long unambiguous alias ('golang') counts
    anywhere; the short form must be capitalised and near a technical word."""
    token = m.group(0)
    if len(token) >= 5:
        return True
    window = text[max(0, m.start() - 60) : m.end() + 60]
    return not token.islower() and bool(_CONTEXT.search(window))


def category_of(name: str) -> str | None:
    s = by_name().get(canonical(name).lower())
    return s.category if s else None
