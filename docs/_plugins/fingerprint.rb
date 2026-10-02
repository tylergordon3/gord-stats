# frozen_string_literal: true

# Content-hashed URLs for the site's own CSS and JS.
#
#   {{ '/assets/js/share.js' | fingerprint | relative_url }}
#     -> /assets/v/<first 12 of the file's MD5>/share.js
#
# Every file under assets/css/ and assets/js/ is also written to
# assets/v/<hash>/<name>, and _headers serves that path as immutable for a
# year. The URL changes exactly when the file does.
#
# Why: the layout used to version every asset with ?v=<build time>. The Pi
# publishes ~80 times on a Saturday, so custom.css (114 KB, render-blocking)
# and seven scripts were downloaded afresh after every one of them - the cache
# never hit. A version that only moves when the file moves keeps the old
# guarantee (a reader never runs the previous build's JavaScript against the
# current HTML - the invisible sign-in control, 2026-09) without the cost.
#
# The hash is in the path, not a query, so `immutable` can be scoped to
# /assets/v/* in _headers: the plain /assets/js/live.js that /men/ and the CBB
# pages load unversioned keeps ordinary revalidation. An unknown path fails
# the build rather than shipping an unversioned URL that looks versioned.
#
# Needs `safe: false` (it is; the Pi builds locally) - GitHub's own Pages
# builder would ignore this directory.

require "digest/md5"

module GordStats
  module Fingerprint
    SOURCE = %r{\A/?assets/(?:css|js)/[^/]+\.(?:css|js)\z}.freeze
    PREFIX = "assets/v"

    # A second copy of a static file, written under its content hash.
    class HashedFile < Jekyll::StaticFile
      def initialize(site, original, digest)
        super(site, site.source, File.dirname(original.relative_path), original.name)
        @digest = digest
      end

      def destination_rel_dir
        File.join(PREFIX, @digest)
      end

      def url
        "/#{PREFIX}/#{@digest}/#{name}"
      end
    end

    class Generator < Jekyll::Generator
      priority :lowest

      def generate(site)
        urls = {}
        site.static_files.select { |f| f.relative_path =~ SOURCE }.each do |file|
          digest = Digest::MD5.file(file.path).hexdigest[0, 12]
          copy = HashedFile.new(site, file, digest)
          site.static_files << copy
          urls["/" + file.relative_path.sub(%r{\A/}, "")] = copy.url
        end
        site.data["fingerprints"] = urls
      end
    end

    module Filter
      def fingerprint(path)
        urls = @context.registers[:site].data["fingerprints"] || {}
        urls.fetch(path.to_s) do
          # A Liquid error, not Ruby's ArgumentError: Liquid reports any other
          # exception as "internal" and the path would be lost.
          raise Liquid::ArgumentError,
                "fingerprint: no hashed copy of #{path.inspect} - only files under " \
                "assets/css/ and assets/js/ get one (docs/_plugins/fingerprint.rb)"
        end
      end
    end
  end
end

Liquid::Template.register_filter(GordStats::Fingerprint::Filter)
