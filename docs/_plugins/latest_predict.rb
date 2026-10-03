# frozen_string_literal: true

# The newest bracketology page per league, for the nav's Bracket links
# (_includes/nav.html reads site.data.latest_predict.men / .women).
#
# Worked out once per build. The nav used to find it with a Liquid loop over
# site.pages, and the nav renders on every page, so the build grew with the
# square of the page count: at 427 pages the loop was ~3 s of a 7 s build; at
# a season of kept game previews (~1,400 pages) it was 32 s of 37 s.
#
# Like the Liquid it replaces, it asks which predict_<date>.html pages exist,
# so nothing changes by hand when a new day's bracket lands.

module GordStats
  class LatestPredict < Jekyll::Generator
    safe true
    priority :lowest

    PATTERN = /\Apredict_(.+)\.html\z/.freeze

    def generate(site)
      latest = { "men" => "", "women" => "" }
      site.pages.each do |page|
        m = PATTERN.match(page.name)
        next unless m

        league = page.dir.delete("/")
        next unless latest.key?(league)

        latest[league] = m[1] if m[1] > latest[league]
      end
      site.data["latest_predict"] = latest
    end
  end
end
