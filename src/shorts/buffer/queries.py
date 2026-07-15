"""GraphQL operation strings for the Buffer API, kept in one place so schema
drift is a one-file fix. Verified against developers.buffer.com (July 2026)."""

ORGANIZATIONS = """
query Organizations {
  account {
    organizations {
      id
      name
    }
  }
}
"""

CHANNELS = """
query Channels($organizationId: OrganizationId!) {
  channels(input: { organizationId: $organizationId }) {
    id
    service
    name
    displayName
  }
}
"""

CREATE_POST = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess {
      post {
        id
        status
        dueAt
      }
    }
    ... on MutationError {
      message
    }
  }
}
"""

POSTS = """
query Posts($input: PostsInput!, $first: Int, $after: String) {
  posts(input: $input, first: $first, after: $after) {
    edges {
      node {
        id
        status
        dueAt
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""
