<?php
/**
 * NDC Hello Child: site-wide Elementor header/footer and the NDC logo.
 *
 * The header and footer are ordinary Elementor templates (Templates > Saved
 * Templates), so they are edited once in the visual editor and appear on every
 * page. This gives free Elementor the part of Elementor Pro's Theme Builder
 * that this site needs. If Elementor Pro is ever installed, its Theme Builder
 * header/footer take priority automatically.
 *
 * @package NDC_Hello_Child
 */

defined( 'ABSPATH' ) || exit;

define( 'NDC_CHILD_VERSION', '1.3.0' );

/** Template titles looked up when nothing is chosen in the Customizer. */
const NDC_PART_TITLES = array(
	'header' => 'NDC Site Header',
	'footer' => 'NDC Site Footer',
);

add_action(
	'wp_enqueue_scripts',
	static function () {
		wp_enqueue_style( 'ndc-hello-child', get_stylesheet_uri(), array(), NDC_CHILD_VERSION );
	},
	20
);

/* -------------------------------------------------------------------------
 * Logo shortcode: [ndc_logo variant="light|dark" height="56" height_mobile="40" link="yes"]
 * "light" is the cream logo for dark backgrounds; "dark" is the black logo.
 * ---------------------------------------------------------------------- */
add_shortcode(
	'ndc_logo',
	static function ( $atts ) {
		$a = shortcode_atts(
			array(
				'variant'       => 'light',
				'height'        => '56',
				'height_mobile' => '',
				'link'          => 'yes',
			),
			$atts,
			'ndc_logo'
		);

		$variant = 'dark' === $a['variant'] ? 'dark' : 'light';
		$height  = max( 16, min( 400, (int) $a['height'] ) );
		$mobile  = $a['height_mobile'] ? max( 16, min( 400, (int) $a['height_mobile'] ) ) : 0;
		$style   = '--ndc-logo-h:' . $height . 'px;' . ( $mobile ? '--ndc-logo-h-mobile:' . $mobile . 'px;' : '' );
		$name    = get_bloginfo( 'name' ) ? get_bloginfo( 'name' ) : 'NDC Consulting Group';

		// Source artwork is 894 x 371; width/height attributes prevent layout shift.
		$img = sprintf(
			'<img class="ndc-logo" src="%1$s" width="%2$d" height="%3$d" alt="%4$s" style="%5$s" decoding="async">',
			esc_url( get_stylesheet_directory_uri() . '/assets/img/ndc-logo-' . $variant . '.png' ),
			(int) round( $height * 894 / 371 ),
			$height,
			esc_attr( $name ),
			esc_attr( $style )
		);

		if ( 'no' === $a['link'] ) {
			return $img;
		}
		return '<a class="ndc-logo-link" href="' . esc_url( home_url( '/' ) ) . '" rel="home">' . $img . '</a>';
	}
);

/* -------------------------------------------------------------------------
 * Site header / footer from Elementor templates
 * ---------------------------------------------------------------------- */

/**
 * Find the Elementor template to use for a site part.
 *
 * @param string $part 'header' or 'footer'.
 * @return int Template post ID, or 0.
 */
function ndc_part_template_id( $part ) {
	$chosen = (int) get_theme_mod( "ndc_{$part}_template", 0 );
	if ( $chosen && 'publish' === get_post_status( $chosen ) ) {
		return $chosen;
	}
	$found = get_posts(
		array(
			'post_type'      => 'elementor_library',
			'post_status'    => 'publish',
			'title'          => NDC_PART_TITLES[ $part ],
			'posts_per_page' => 1,
			'orderby'        => 'ID',
			'order'          => 'DESC',
			'fields'         => 'ids',
			'no_found_rows'  => true,
		)
	);
	if ( $found ) {
		return (int) $found[0];
	}
	// Tolerate renamed copies such as "NDC Site Header (1)" or different case.
	foreach ( get_posts(
		array(
			'post_type'      => 'elementor_library',
			'post_status'    => 'publish',
			's'              => NDC_PART_TITLES[ $part ],
			'posts_per_page' => 10,
			'orderby'        => 'ID',
			'order'          => 'DESC',
		)
	) as $tpl ) {
		if ( 0 === stripos( trim( $tpl->post_title ), NDC_PART_TITLES[ $part ] ) ) {
			return (int) $tpl->ID;
		}
	}
	return 0;
}

/**
 * Print a site part. Returns false if no template is available, so the
 * caller can fall back to Hello's default header/footer.
 *
 * @param string $part 'header' or 'footer'.
 * @return bool
 */
function ndc_render_part( $part ) {
	if ( ! did_action( 'elementor/loaded' ) || ! class_exists( '\Elementor\Plugin' ) ) {
		return false;
	}
	$id = ndc_part_template_id( $part );
	if ( ! $id ) {
		return false;
	}
	$html = \Elementor\Plugin::instance()->frontend->get_builder_content_for_display( $id, true );
	if ( '' === trim( (string) $html ) ) {
		return false;
	}
	$tag = 'header' === $part ? 'header' : 'footer';
	printf( '<%1$s id="site-%1$s" class="ndc-site-%1$s">%2$s</%1$s>', $tag, $html ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- Elementor output.
	return true;
}

/* -------------------------------------------------------------------------
 * Customizer: Appearance > Customize > NDC Header & Footer
 * ---------------------------------------------------------------------- */
add_action(
	'customize_register',
	static function ( WP_Customize_Manager $wp_customize ) {
		$choices = array( 0 => __( '— Automatic (by template name) —', 'ndc-hello-child' ) );
		foreach ( get_posts(
			array(
				'post_type'      => 'elementor_library',
				'post_status'    => 'publish',
				'posts_per_page' => 200,
				'orderby'        => 'title',
				'order'          => 'ASC',
			)
		) as $tpl ) {
			$choices[ $tpl->ID ] = $tpl->post_title;
		}

		$wp_customize->add_section(
			'ndc_parts',
			array(
				'title'       => __( 'NDC Header & Footer', 'ndc-hello-child' ),
				'description' => sprintf(
					/* translators: 1: header template title, 2: footer template title. */
					__( 'Choose which Elementor templates appear at the top and bottom of every page. "Automatic" uses the templates named "%1$s" and "%2$s".', 'ndc-hello-child' ),
					NDC_PART_TITLES['header'],
					NDC_PART_TITLES['footer']
				),
				'priority'    => 30,
			)
		);
		foreach ( array( 'header', 'footer' ) as $part ) {
			$wp_customize->add_setting(
				"ndc_{$part}_template",
				array(
					'default'           => 0,
					'sanitize_callback' => 'absint',
				)
			);
			$wp_customize->add_control(
				"ndc_{$part}_template",
				array(
					'section' => 'ndc_parts',
					'label'   => 'header' === $part ? __( 'Header template', 'ndc-hello-child' ) : __( 'Footer template', 'ndc-hello-child' ),
					'type'    => 'select',
					'choices' => $choices,
				)
			);
		}
	}
);

/* -------------------------------------------------------------------------
 * Built-in header/footer: used only if the Elementor templates can't be
 * found or rendered, so the logo and navigation always appear.
 * ---------------------------------------------------------------------- */
function ndc_builtin_part( $part ) {
	if ( 'header' === $part ) {
		$links = array(
			__( 'About', 'ndc-hello-child' )      => array( home_url( '/#about' ), true ),
			__( 'Services', 'ndc-hello-child' )   => array( home_url( '/#services' ), true ),
			__( 'Process', 'ndc-hello-child' )    => array( home_url( '/#process' ), true ),
			__( 'Contact Us', 'ndc-hello-child' ) => array( home_url( '/contact/' ), false ),
		);
		$nav = '';
		foreach ( $links as $label => $link ) {
			$nav .= '<a href="' . esc_url( $link[0] ) . '"' . ( $link[1] ? ' class="ndc-builtin__hide-mobile"' : '' ) . '>' . esc_html( $label ) . '</a>';
		}
		echo '<header id="site-header" class="ndc-builtin ndc-builtin--header"><div class="ndc-builtin__inner">' . do_shortcode( '[ndc_logo height="64" height_mobile="46"]' ) // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
			. '<nav class="ndc-builtin__nav" aria-label="' . esc_attr__( 'Main', 'ndc-hello-child' ) . '">' . $nav . '</nav></div></header>'; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
		return;
	}
	$email = 'nadiaworsley@gmail.com';
	echo '<footer id="site-footer" class="ndc-builtin ndc-builtin--footer"><div class="ndc-builtin__inner">'
		. '<a href="' . esc_url( 'mailto:' . $email ) . '">' . esc_html( $email ) . '</a>'
		. '<span class="ndc-builtin__legal">' . esc_html( sprintf( 'Copyright %s © NDC Consulting Group', wp_date( 'Y' ) ) ) . '</span>'
		. '</div></footer>';
}

/* -------------------------------------------------------------------------
 * Auto-import: bring in the bundled header/footer templates if missing.
 * ---------------------------------------------------------------------- */
function ndc_import_missing_parts( $force = false ) {
	if ( ! did_action( 'elementor/loaded' ) || ! class_exists( '\Elementor\Plugin' ) || ! current_user_can( 'manage_options' ) ) {
		return array();
	}
	$source = \Elementor\Plugin::$instance->templates_manager->get_source( 'local' );
	if ( ! $source ) {
		return array();
	}
	$done = array();
	foreach ( array( 'header', 'footer' ) as $part ) {
		if ( ! $force && ndc_part_template_id( $part ) ) {
			continue;
		}
		$file = get_stylesheet_directory() . "/templates/ndc-{$part}.json";
		if ( ! is_readable( $file ) ) {
			continue;
		}
		$result = $source->import_template( basename( $file ), $file );
		if ( ! is_wp_error( $result ) && ! empty( $result[0]['template_id'] ) ) {
			$done[ $part ] = (int) $result[0]['template_id'];
			set_theme_mod( "ndc_{$part}_template", $done[ $part ] );
		}
	}
	return $done;
}

/**
 * Replace the content of the existing header/footer templates with the
 * versions bundled in this theme. Keeps the template IDs (so nothing else
 * needs re-selecting) and stores a backup of the previous content.
 *
 * @return string[] Parts that were updated.
 */
function ndc_update_parts_from_theme() {
	if ( ! did_action( 'elementor/loaded' ) || ! class_exists( '\Elementor\Plugin' ) ) {
		return array();
	}
	$updated = array();
	foreach ( array( 'header', 'footer' ) as $part ) {
		$id   = ndc_part_template_id( $part );
		$file = get_stylesheet_directory() . "/templates/ndc-{$part}.json";
		$json = is_readable( $file ) ? json_decode( (string) file_get_contents( $file ), true ) : null; // phpcs:ignore WordPress.WP.AlternativeFunctions.file_get_contents_file_get_contents
		if ( ! $id || empty( $json['content'] ) ) {
			continue;
		}
		$old = (string) get_post_meta( $id, '_elementor_data', true );
		if ( $old ) {
			update_post_meta( $id, '_ndc_previous_elementor_data', wp_slash( $old ) );
		}
		$document = \Elementor\Plugin::$instance->documents->get( $id, false );
		if ( $document ) {
			$document->save( array( 'elements' => $json['content'] ) );
			$updated[] = $part;
		}
	}
	if ( $updated ) {
		\Elementor\Plugin::$instance->files_manager->clear_cache();
	}
	return $updated;
}

add_action(
	'admin_init',
	static function () {
		$installed = (string) get_option( 'ndc_parts_imported' );
		if ( wp_doing_ajax() || $installed === NDC_CHILD_VERSION ) {
			return;
		}
		if ( did_action( 'elementor/loaded' ) && current_user_can( 'manage_options' ) ) {
			ndc_import_missing_parts();
			// After a theme update, bring the header/footer up to the new design.
			if ( $installed && version_compare( $installed, NDC_CHILD_VERSION, '<' ) ) {
				ndc_update_parts_from_theme();
			}
			update_option( 'ndc_parts_imported', NDC_CHILD_VERSION, false );
		}
	}
);

/* -------------------------------------------------------------------------
 * Appearance > NDC Site Status: shows what is working, with a repair button.
 * ---------------------------------------------------------------------- */
add_action(
	'admin_menu',
	static function () {
		add_theme_page( __( 'NDC Site Status', 'ndc-hello-child' ), __( 'NDC Site Status', 'ndc-hello-child' ), 'manage_options', 'ndc-site-status', 'ndc_status_page' );
	}
);

function ndc_status_page() {
	$notice = '';
	if ( isset( $_POST['ndc_repair'] ) && check_admin_referer( 'ndc_repair' ) ) {
		$done   = ndc_import_missing_parts( true );
		$notice = $done ? __( 'Header and footer re-imported and selected.', 'ndc-hello-child' ) : __( 'Nothing was imported. Is Elementor active?', 'ndc-hello-child' );
		if ( class_exists( '\Elementor\Plugin' ) ) {
			\Elementor\Plugin::$instance->files_manager->clear_cache();
		}
	}
	$parent = wp_get_theme( 'hello-elementor' );
	$rows   = array(
		__( 'Active theme', 'ndc-hello-child' )      => array( 'ndc-hello-child' === get_stylesheet(), wp_get_theme()->get( 'Name' ) . ' ' . wp_get_theme()->get( 'Version' ) ),
		__( 'Hello Elementor (parent)', 'ndc-hello-child' ) => array( $parent->exists(), $parent->exists() ? $parent->get( 'Version' ) : __( 'not installed', 'ndc-hello-child' ) ),
		__( 'Elementor plugin', 'ndc-hello-child' )  => array( defined( 'ELEMENTOR_VERSION' ), defined( 'ELEMENTOR_VERSION' ) ? ELEMENTOR_VERSION : __( 'not active', 'ndc-hello-child' ) ),
		__( 'Elementor Pro', 'ndc-hello-child' )     => array( true, defined( 'ELEMENTOR_PRO_VERSION' ) ? ELEMENTOR_PRO_VERSION . ' — ' . __( 'its Theme Builder header/footer, if any, take priority', 'ndc-hello-child' ) : __( 'not installed (fine)', 'ndc-hello-child' ) ),
	);
	foreach ( array( 'header', 'footer' ) as $part ) {
		$id = ndc_part_template_id( $part );
		$rows[ 'header' === $part ? __( 'Header template', 'ndc-hello-child' ) : __( 'Footer template', 'ndc-hello-child' ) ] = array( (bool) $id, $id ? get_the_title( $id ) . " (#{$id})" : __( 'not found — the built-in header/footer is shown instead', 'ndc-hello-child' ) );
	}
	if ( class_exists( 'NDC_Contact_Form' ) ) {
		$form      = NDC_Contact_Form::settings();
		$turnstile = $form['turnstile_site_key'] && $form['turnstile_secret_key'];
		$rows[ __( 'Contact form', 'ndc-hello-child' ) ] = array( true, sprintf( __( 'active — enquiries go to %s', 'ndc-hello-child' ), $form['recipient'] ) );
		$rows[ __( 'Cloudflare Turnstile', 'ndc-hello-child' ) ] = array( $turnstile, $turnstile ? __( 'on', 'ndc-hello-child' ) : __( 'off — add the Site key and Secret key under Settings → NDC Contact Form', 'ndc-hello-child' ) );
	} else {
		$rows[ __( 'Contact form', 'ndc-hello-child' ) ] = array( false, __( 'NDC Contact Form plugin not active', 'ndc-hello-child' ) );
	}
	$logo = get_stylesheet_directory() . '/assets/img/ndc-logo-light.png';
	$rows[ __( 'Logo files', 'ndc-hello-child' ) ] = array( is_readable( $logo ), is_readable( $logo ) ? __( 'present', 'ndc-hello-child' ) : __( 'missing', 'ndc-hello-child' ) );
	?>
	<div class="wrap">
		<h1><?php esc_html_e( 'NDC Site Status', 'ndc-hello-child' ); ?></h1>
		<?php if ( $notice ) : ?><div class="notice notice-success"><p><?php echo esc_html( $notice ); ?></p></div><?php endif; ?>
		<table class="widefat striped" style="max-width:820px">
			<tbody>
			<?php foreach ( $rows as $label => $row ) : ?>
				<tr><td style="width:240px"><strong><?php echo esc_html( $label ); ?></strong></td>
					<td><?php echo $row[0] ? '&#9989; ' : '&#10060; '; ?><?php echo esc_html( $row[1] ); ?></td></tr>
			<?php endforeach; ?>
			</tbody>
		</table>
		<form method="post" style="margin-top:20px">
			<?php wp_nonce_field( 'ndc_repair' ); ?>
			<p><?php esc_html_e( 'Re-import the NDC header and footer from the theme, select them, and clear Elementor\'s cache:', 'ndc-hello-child' ); ?></p>
			<?php submit_button( __( 'Repair header & footer', 'ndc-hello-child' ), 'primary', 'ndc_repair', false ); ?>
		</form>
		<?php do_action( 'ndc_status_page_after' ); ?>
	</div>
	<?php
}

/* -------------------------------------------------------------------------
 * Page check: pages built from the first NDC templates had their own header
 * and footer inside the page and used the "Elementor Canvas" layout, which
 * hides the site header/footer. These helpers find and fix such pages.
 * ---------------------------------------------------------------------- */

/** Recursively drop old built-in header/footer containers. */
function ndc_strip_embedded_parts( array $elements, $depth = 0, &$removed = 0 ) {
	$out = array();
	foreach ( $elements as $el ) {
		$tag = $el['settings']['html_tag'] ?? '';
		if ( ( 'header' === $tag && 0 === $depth ) || 'footer' === $tag ) {
			++$removed;
			continue;
		}
		if ( ! empty( $el['elements'] ) && is_array( $el['elements'] ) ) {
			$el['elements'] = ndc_strip_embedded_parts( $el['elements'], $depth + 1, $removed );
		}
		$out[] = $el;
	}
	return $out;
}

/** @return string[] Problems found on a page. */
function ndc_page_issues( $post_id ) {
	$issues = array();
	if ( 'elementor_canvas' === get_page_template_slug( $post_id ) ) {
		$issues[] = 'canvas';
	}
	$data = json_decode( (string) get_post_meta( $post_id, '_elementor_data', true ), true );
	if ( is_array( $data ) ) {
		$removed = 0;
		ndc_strip_embedded_parts( $data, 0, $removed );
		if ( $removed ) {
			$issues[] = 'embedded';
		}
	}
	return $issues;
}

/** Pages to check: the homepage plus every Elementor page. */
function ndc_pages_to_check() {
	$ids = get_posts(
		array(
			'post_type'      => 'page',
			'post_status'    => array( 'publish', 'draft', 'private' ),
			'posts_per_page' => 100,
			'fields'         => 'ids',
			'meta_key'       => '_elementor_edit_mode', // phpcs:ignore WordPress.DB.SlowDBQuery.slow_db_query_meta_key
			'meta_value'     => 'builder', // phpcs:ignore WordPress.DB.SlowDBQuery.slow_db_query_meta_value
		)
	);
	$front = (int) get_option( 'page_on_front' );
	if ( $front && ! in_array( $front, $ids, true ) ) {
		array_unshift( $ids, $front );
	}
	return $ids;
}

/** Fix one page: Full Width layout and no embedded header/footer. Keeps a backup. */
function ndc_fix_page( $post_id ) {
	$raw  = (string) get_post_meta( $post_id, '_elementor_data', true );
	$data = json_decode( $raw, true );
	if ( is_array( $data ) ) {
		$removed = 0;
		$clean   = ndc_strip_embedded_parts( $data, 0, $removed );
		if ( $removed ) {
			if ( ! get_post_meta( $post_id, '_ndc_backup_elementor_data', true ) ) {
				update_post_meta( $post_id, '_ndc_backup_elementor_data', wp_slash( $raw ) );
			}
			update_post_meta( $post_id, '_elementor_data', wp_slash( wp_json_encode( $clean ) ) );
		}
	}
	if ( 'elementor_canvas' === get_page_template_slug( $post_id ) ) {
		update_post_meta( $post_id, '_wp_page_template', 'elementor_header_footer' );
		$settings = get_post_meta( $post_id, '_elementor_page_settings', true );
		if ( is_array( $settings ) ) {
			$settings['template'] = 'elementor_header_footer';
			update_post_meta( $post_id, '_elementor_page_settings', $settings );
		}
	}
	delete_post_meta( $post_id, '_elementor_css' );
	delete_post_meta( $post_id, '_elementor_element_cache' );
}

/** Restore a page from the backup made by ndc_fix_page(). */
function ndc_restore_page( $post_id ) {
	$backup = get_post_meta( $post_id, '_ndc_backup_elementor_data', true );
	if ( $backup ) {
		update_post_meta( $post_id, '_elementor_data', wp_slash( $backup ) );
		delete_post_meta( $post_id, '_ndc_backup_elementor_data' );
		delete_post_meta( $post_id, '_elementor_css' );
		delete_post_meta( $post_id, '_elementor_element_cache' );
	}
}

/** Pages section of Appearance > NDC Site Status. */
add_action(
	'ndc_status_page_after',
	static function () {
		$notice = '';
		if ( isset( $_POST['ndc_fix_pages'] ) && check_admin_referer( 'ndc_fix_pages' ) ) {
			$fixed = 0;
			foreach ( ndc_pages_to_check() as $id ) {
				if ( ndc_page_issues( $id ) ) {
					ndc_fix_page( $id );
					++$fixed;
				}
			}
			if ( class_exists( '\Elementor\Plugin' ) ) {
				\Elementor\Plugin::$instance->files_manager->clear_cache();
			}
			/* translators: %d: number of pages. */
			$notice = sprintf( _n( 'Fixed %d page.', 'Fixed %d pages.', $fixed, 'ndc-hello-child' ), $fixed );
		}
		if ( isset( $_POST['ndc_restore_page'] ) && check_admin_referer( 'ndc_fix_pages' ) ) {
			ndc_restore_page( absint( $_POST['ndc_restore_page'] ) );
			if ( class_exists( '\Elementor\Plugin' ) ) {
				\Elementor\Plugin::$instance->files_manager->clear_cache();
			}
			$notice = __( 'Page restored from backup.', 'ndc-hello-child' );
		}

		$labels = array(
			'canvas'   => __( 'uses the "Elementor Canvas" layout, which hides the site header and footer', 'ndc-hello-child' ),
			'embedded' => __( 'still has the old header/footer built into the page', 'ndc-hello-child' ),
		);
		$front   = (int) get_option( 'page_on_front' );
		$pending = 0;
		?>
		<h2 style="margin-top:32px"><?php esc_html_e( 'Pages', 'ndc-hello-child' ); ?></h2>
		<?php if ( $notice ) : ?><div class="notice notice-success"><p><?php echo esc_html( $notice ); ?></p></div><?php endif; ?>
		<?php if ( ! $front ) : ?>
			<p>&#10060; <?php esc_html_e( 'No homepage is set. Go to Settings → Reading → "A static page" and choose Home.', 'ndc-hello-child' ); ?></p>
		<?php endif; ?>
		<form method="post">
			<?php wp_nonce_field( 'ndc_fix_pages' ); ?>
			<table class="widefat striped" style="max-width:820px">
				<tbody>
				<?php foreach ( ndc_pages_to_check() as $id ) : ?>
					<?php
					$issues   = ndc_page_issues( $id );
					$pending += $issues ? 1 : 0;
					?>
					<tr>
						<td style="width:240px"><strong><?php echo esc_html( get_the_title( $id ) ); ?></strong><?php echo $id === $front ? ' <em>(' . esc_html__( 'homepage', 'ndc-hello-child' ) . ')</em>' : ''; ?></td>
						<td>
							<?php if ( $issues ) : ?>
								&#10060; <?php echo esc_html( implode( '; ', array_map( static fn( $i ) => $labels[ $i ], $issues ) ) ); ?>
							<?php else : ?>
								&#9989; <?php esc_html_e( 'OK', 'ndc-hello-child' ); ?>
							<?php endif; ?>
							<?php if ( get_post_meta( $id, '_ndc_backup_elementor_data', true ) ) : ?>
								<button class="button-link" name="ndc_restore_page" value="<?php echo esc_attr( $id ); ?>" style="margin-left:12px"><?php esc_html_e( 'Undo fix', 'ndc-hello-child' ); ?></button>
							<?php endif; ?>
						</td>
					</tr>
				<?php endforeach; ?>
				</tbody>
			</table>
			<?php if ( $pending ) : ?>
				<p><?php esc_html_e( 'Switch these pages to "Elementor Full Width" and remove the old built-in header/footer, so the site header and footer with the logo show. A backup of each page is kept.', 'ndc-hello-child' ); ?></p>
				<?php submit_button( __( 'Fix pages', 'ndc-hello-child' ), 'primary', 'ndc_fix_pages', false ); ?>
			<?php endif; ?>
		</form>
		<?php
	}
);

/** Point admins at the status page while any page still needs fixing. */
add_action(
	'admin_notices',
	static function () {
		if ( ! current_user_can( 'manage_options' ) || ( isset( $_GET['page'] ) && 'ndc-site-status' === $_GET['page'] ) ) { // phpcs:ignore WordPress.Security.NonceVerification.Recommended
			return;
		}
		$front = (int) get_option( 'page_on_front' );
		if ( $front && ndc_page_issues( $front ) ) {
			printf(
				'<div class="notice notice-warning"><p>%s <a href="%s">%s</a></p></div>',
				esc_html__( 'Your homepage was built from an earlier NDC template and is hiding the site header and footer.', 'ndc-hello-child' ),
				esc_url( admin_url( 'themes.php?page=ndc-site-status' ) ),
				esc_html__( 'Fix it on the NDC Site Status page →', 'ndc-hello-child' )
			);
		}
	}
);
