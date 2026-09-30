# Minimize reader load

Pillar: comprehension

**Rule.** Count the layers between a reader's question and its answer, and the state they must hold in their head to follow the code. Reduce both.

**Applies when.** Adding an abstraction, reviewing code that is hard to trace, or naming things.

**Changes.** You inline wrappers that have one caller, keep mutable state in the smallest scope, and name things for what they are in the domain. An abstraction earns its place with a second real caller.

**Counter-example.** A `FeedManager` that calls a `FeedService` that calls a `FeedRepository`, each passing the same arguments through unchanged.
